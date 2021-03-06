import os
import os.path as op
import sys

from pyrevit import PyRevitException
from pyrevit.coreutils import make_canonical_name, find_loaded_asm, load_asm_file, calculate_dir_hash,\
                              find_type_by_name, read_source_file
from pyrevit.coreutils.logger import get_logger
from pyrevit.coreutils.dotnetcompiler import compile_csharp
from pyrevit.versionmgr import PYREVIT_VERSION
import pyrevit.coreutils.appdata as appdata

from pyrevit.loader import ASSEMBLY_FILE_TYPE, HASH_CUTOFF_LENGTH


logger = get_logger(__name__)


# folders --------------------------------------------------------------------------------------------------------------
LOADER_DIR = op.dirname(op.dirname(__file__))
ADDIN_DIR = op.join(LOADER_DIR, 'addin')

sys.path.append(ADDIN_DIR)

ADDIN_RESOURCE_DIR = op.join(ADDIN_DIR, 'Source', 'pyRevitLoader', 'Resources')
INTERFACE_TYPES_DIR = op.join(LOADER_DIR, 'basetypes')

DOTNET_SDK_DIR = op.join(os.getenv('programfiles(x86)'),
                         'Reference Assemblies', 'Microsoft', 'Framework', '.NETFramework')

try:
    FRAMEWORK_DIRS = os.listdir(DOTNET_SDK_DIR)
except Exception as dotnet_sdk_err:
    FRAMEWORK_DIRS = None
    logger.debug('Dotnet SDK is not installed. | {}'.format(dotnet_sdk_err))


# base classes for pyRevit commands ------------------------------------------------------------------------------------
LOADER_BASE_NAMESPACE = 'PyRevitBaseClasses'

# template python command class
CMD_EXECUTOR_TYPE_NAME = '{}.{}'.format(LOADER_BASE_NAMESPACE, 'PyRevitCommand')

# template python command availability class
CMD_AVAIL_TYPE_NAME = make_canonical_name(LOADER_BASE_NAMESPACE, 'PyRevitCommandDefaultAvail')
CMD_AVAIL_TYPE_NAME_CATEGORY = make_canonical_name(LOADER_BASE_NAMESPACE, 'PyRevitCommandCategoryAvail')
CMD_AVAIL_TYPE_NAME_SELECTION = make_canonical_name(LOADER_BASE_NAMESPACE, 'PyRevitCommandSelectionAvail')

source_file_filter = '(\.cs)'
BASE_TYPES_DIR_HASH = calculate_dir_hash(INTERFACE_TYPES_DIR, '', source_file_filter)[:HASH_CUTOFF_LENGTH]
BASE_TYPES_ASM_FILE_ID = '{}_{}'.format(BASE_TYPES_DIR_HASH, LOADER_BASE_NAMESPACE)
BASE_TYPES_ASM_FILE = appdata.get_data_file(BASE_TYPES_ASM_FILE_ID, ASSEMBLY_FILE_TYPE)
# taking the name of the generated data file and use it as assembly name
BASE_TYPES_ASM_NAME = op.splitext(op.basename(BASE_TYPES_ASM_FILE))[0]
logger.debug('Interface types assembly file is: {}'.format(BASE_TYPES_ASM_NAME))


def _get_asm_attr_source():
    asm_att_source = """
    using System.Reflection;
    using System.Runtime.CompilerServices;
    using System.Runtime.InteropServices;
    using PyRevitBaseClasses;
    [assembly: AssemblyPyRevitVersion("{}")]
    """.format(PYREVIT_VERSION.get_formatted())

    return asm_att_source


def _get_source_files():
    source_files = list()
    source_dir = op.dirname(__file__)
    logger.debug('Source files location: {}'.format(source_dir))
    for source_file in os.listdir(source_dir):
        if op.splitext(source_file)[1].lower() == '.cs':
            logger.debug('Source file found: {}'.format(source_file))
            source_files.append(op.join(source_dir, source_file))

    logger.debug('Source files to be compiled: {}'.format(source_files))
    return source_files


def _get_resource_file(resource_name):
    return op.join(ADDIN_RESOURCE_DIR, resource_name)


def _get_framework_module(fw_module):
    # start with the newest sdk folder and work backwards trying to find the dll
    for sdk_folder in reversed(FRAMEWORK_DIRS):
        fw_module_file = op.join(DOTNET_SDK_DIR, sdk_folder, make_canonical_name(fw_module, ASSEMBLY_FILE_TYPE))
        if op.exists(fw_module_file):
            sys.path.append(op.join(DOTNET_SDK_DIR, sdk_folder))
            return fw_module_file

    return None


def _get_addin_dll_file(addin_filename):
    addin_file = op.join(ADDIN_DIR, make_canonical_name(addin_filename, ASSEMBLY_FILE_TYPE))
    if op.exists(addin_file):
        return addin_file

    return None


def _get_reference_file(ref_name):
    # First try to find the dll in the project folder
    addin_file = _get_addin_dll_file(ref_name)
    if addin_file:
        return addin_file

    # Then try to find the dll in windows SDK
    if FRAMEWORK_DIRS:
        fw_module_file = _get_framework_module(ref_name)
        if fw_module_file:
            return fw_module_file

    # Lastly try to find location of assembly if already loaded
    loaded_asm = find_loaded_asm(ref_name)
    if loaded_asm:
        return loaded_asm[0].Location

    # if not worked raise critical error
    logger.critical('Can not find required reference assembly: {}'.format(ref_name))


def _get_references():
    ref_list = ['RevitAPI', 'RevitAPIUI', 'IronPython', 'IronPython.Modules',
                'Microsoft.Dynamic', 'Microsoft.Scripting', 'Microsoft.CSharp',
                'System', 'System.Core', 'System.Drawing', 'System.Windows.Forms',
                'PresentationCore', 'PresentationFramework', 'WindowsBase']

    return [_get_reference_file(ref_name) for ref_name in ref_list]


def _generate_base_classes_asm():
    source_list = list()
    source_list.append(_get_asm_attr_source())
    for source_file in _get_source_files():
        source_list.append(read_source_file(source_file))

    # now try to compile
    try:
        logger.debug('Compiling base types to: {}'.format(BASE_TYPES_ASM_FILE))
        # compile_csharp(source_list, BASE_TYPES_ASM_FILE,
        #                reference_list=_get_references(), resource_list=[_get_resource_file('python_27_lib.zip')])
        compile_csharp(source_list, BASE_TYPES_ASM_FILE,
                       reference_list=_get_references())
        return load_asm_file(BASE_TYPES_ASM_FILE)

    except PyRevitException as compile_err:
        logger.critical('Can not compile base types code into assembly. | {}'.format(compile_err))
        raise compile_err


def _get_base_classes_asm():
    if appdata.is_data_file_available(file_id=BASE_TYPES_ASM_FILE_ID, file_ext=ASSEMBLY_FILE_TYPE):
        return load_asm_file(BASE_TYPES_ASM_FILE)
    else:
        return _generate_base_classes_asm()


# compile or load the base types assembly ------------------------------------------------------------------------------
# see it the assembly is already loaded
BASE_TYPES_ASM = None
assm_list = find_loaded_asm(BASE_TYPES_ASM_NAME)
if assm_list:
    BASE_TYPES_ASM = assm_list[0]
else:
    # else, let's generate the assembly and load it
    BASE_TYPES_ASM = _get_base_classes_asm()


CMD_EXECUTOR_TYPE = find_type_by_name(BASE_TYPES_ASM, CMD_EXECUTOR_TYPE_NAME)
CMD_AVAIL_TYPE = find_type_by_name(BASE_TYPES_ASM, CMD_AVAIL_TYPE_NAME)
CMD_AVAIL_TYPE_CATEGORY = find_type_by_name(BASE_TYPES_ASM, CMD_AVAIL_TYPE_NAME_CATEGORY)
CMD_AVAIL_TYPE_SELECTION = find_type_by_name(BASE_TYPES_ASM, CMD_AVAIL_TYPE_NAME_SELECTION)
