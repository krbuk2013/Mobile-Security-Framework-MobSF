# -*- coding: utf_8 -*-
"""Module for iOS IPA Binary Analysis."""

import logging
import os
import platform
import re
import subprocess

from django.conf import settings
from django.utils.encoding import smart_text
from django.utils.html import escape

from macholib.mach_o import (CPU_TYPE_NAMES, MH_CIGAM_64, MH_MAGIC_64,
                             get_cpu_subtype)
from macholib.MachO import MachO

from MobSF.utils import is_file_exists

from StaticAnalyzer.tools.strings import strings_util

logger = logging.getLogger(__name__)
SECURE = 'Secure'
IN_SECURE = 'Insecure'
INFO = 'Info'
WARNING = 'Warning'


def get_otool_out(tools_dir, cmd_type, bin_path, bin_dir):
    """Get otool args by OS and type."""
    if (len(settings.OTOOL_BINARY) > 0
            and is_file_exists(settings.OTOOL_BINARY)):
        otool_bin = settings.OTOOL_BINARY
    else:
        otool_bin = 'otool'
    if (len(settings.JTOOL_BINARY) > 0
            and is_file_exists(settings.JTOOL_BINARY)):
        jtool_bin = settings.JTOOL_BINARY
    else:
        jtool_bin = os.path.join(tools_dir, 'jtool.ELF64')
    plat = platform.system()
    if cmd_type == 'libs':
        if plat == 'Darwin':
            args = [otool_bin, '-L', bin_path]
        elif plat == 'Linux':
            args = [jtool_bin, '-arch', 'arm', '-L', '-v', bin_path]
        else:
            # Platform Not Supported
            return None
        libs = subprocess.check_output(args).decode('utf-8', 'ignore')
        libs = smart_text(escape(libs.replace(bin_dir + '/', '')))
        return libs.split('\n')
    elif cmd_type == 'header':
        if plat == 'Darwin':
            args = [otool_bin, '-hv', bin_path]
        elif plat == 'Linux':
            args = [jtool_bin, '-arch', 'arm', '-h', '-v', bin_path]
        else:
            # Platform Not Supported
            return None
        return subprocess.check_output(args)
    elif cmd_type == 'symbols':
        if plat == 'Darwin':
            args = [otool_bin, '-Iv', bin_path]
            return subprocess.check_output(args)
        elif plat == 'Linux':
            arg1 = [jtool_bin, '-arch', 'arm', '-bind', '-v', bin_path]
            arg2 = [jtool_bin, '-arch', 'arm', '-lazy_bind', '-v', bin_path]
            return (subprocess.check_output(arg1)
                    + subprocess.check_output(arg2))
        else:
            # Platform Not Supported
            return None


def otool_analysis(tools_dir, bin_name, bin_path, bin_dir):
    """OTOOL Analysis of Binary."""
    try:
        otool_dict = {
            'libs': [],
            'anal': [],
        }
        logger.info('Running Object Analysis of Binary : %s', bin_name)
        otool_dict['libs'] = get_otool_out(
            tools_dir, 'libs', bin_path, bin_dir)
        # PIE
        pie_dat = get_otool_out(tools_dir, 'header', bin_path, bin_dir)
        if b'PIE' in pie_dat:
            pie_flag = {
                'issue': 'fPIE -pie flag is Found',
                'status': SECURE,
                'description': ('App is compiled with Position Independent '
                                'Executable (PIE) flag. This enables Address'
                                ' Space Layout Randomization (ASLR), a memory'
                                ' protection mechanism for'
                                ' exploit mitigation.'),
                'cvss': 0,
                'cwe': '',
            }
        else:
            pie_flag = {
                'issue': 'fPIE -pie flag is not Found',
                'status': IN_SECURE,
                'description': ('with Position Independent Executable (PIE) '
                                'flag. So Address Space Layout Randomization '
                                '(ASLR) is missing. ASLR is a memory '
                                'protection mechanism for '
                                'exploit mitigation.'),
                'cvss': 2,
                'cwe': 'CWE-119',
            }
        # Stack Smashing Protection & ARC
        dat = get_otool_out(tools_dir, 'symbols', bin_path, bin_dir)
        if b'stack_chk_guard' in dat:
            ssmash = {
                'issue': 'fstack-protector-all flag is Found',
                'status': SECURE,
                'description': ('App is compiled with Stack Smashing Protector'
                                ' (SSP) flag and is having protection against'
                                ' Stack Overflows/Stack Smashing Attacks.'),
                'cvss': 0,
                'cwe': ''}
        else:
            ssmash = {
                'issue': 'fstack-protector-all flag is not Found',
                'status': IN_SECURE,
                'description': ('App is not compiled with Stack Smashing '
                                'Protector (SSP) flag. It is vulnerable to'
                                'Stack Overflows/Stack Smashing Attacks.'),
                'cvss': 2,
                'cwe': 'CWE-119'}

        # ARC
        if b'_objc_release' in dat:
            arc_flag = {
                'issue': 'fobjc-arc flag is Found',
                'status': SECURE,
                'description': ('App is compiled with Automatic Reference '
                                'Counting (ARC) flag. ARC is a compiler '
                                'feature that provides automatic memory '
                                'management of Objective-C objects and is an '
                                'exploit mitigation mechanism against memory '
                                'corruption vulnerabilities.'),
                'cvss': 0,
                'cwe': ''}
        else:
            arc_flag = {
                'issue': 'fobjc-arc flag is not Found',
                'status': IN_SECURE,
                'description': ('App is not compiled with Automatic Reference '
                                'Counting (ARC) flag. ARC is a compiler '
                                'feature that provides automatic memory '
                                'management of Objective-C objects and '
                                'protects from memory corruption '
                                'vulnerabilities.'),
                'cvss': 2,
                'cwe': 'CWE-119'}

        banned_apis = {}
        baned = re.findall(
            b'_alloca|_gets|_memcpy|_printf|_scanf|_sprintf|_sscanf|_strcat|'
            b'StrCat|_strcpy|StrCpy|_strlen|StrLen|_strncat|StrNCat|_strncpy|'
            b'StrNCpy|_strtok|_swprintf|_vsnprintf|_vsprintf|_vswprintf|'
            b'_wcscat|_wcscpy|_wcslen|_wcsncat|_wcsncpy|_wcstok|_wmemcpy|'
            b'_fopen|_chmod|_chown|_stat|_mktemp', dat)
        baned = list(set(baned))
        baned_s = b', '.join(baned)
        if len(baned_s) > 1:
            banned_apis = {
                'issue': 'Binary make use of banned API(s)',
                'status': IN_SECURE,
                'description': ('The binary may contain'
                                ' the following banned API(s) {}.').format(
                                    baned_s.decode('utf-8', 'ignore')),
                'cvss': 6,
                'cwe': 'CWE-676'}

        weak_cryptos = {}
        weak_algo = re.findall(
            b'kCCAlgorithmDES|kCCAlgorithm3DES||kCCAlgorithmRC2|'
            b'kCCAlgorithmRC4|kCCOptionECBMode|kCCOptionCBCMode', dat)
        weak_algo = list(set(weak_algo))
        weak_algo_s = b', '.join(weak_algo)
        if len(weak_algo_s) > 1:
            weak_cryptos = {
                'issue': 'Binary make use of some Weak Crypto API(s)',
                'status': IN_SECURE,
                'description': ('The binary may use the'
                                ' following weak crypto API(s) {}.').formnat(
                                    weak_algo_s.decode('utf-8', 'ignore')),
                'cvss': 3,
                'cwe': 'CWE-327'}

        crypto = {}
        crypto_algo = re.findall(
            b'CCKeyDerivationPBKDF|CCCryptorCreate|CCCryptorCreateFromData|'
            b'CCCryptorRelease|CCCryptorUpdate|CCCryptorFinal|'
            b'CCCryptorGetOutputLength|CCCryptorReset|CCCryptorRef|kCCEncrypt|'
            b'kCCDecrypt|kCCAlgorithmAES128|kCCKeySizeAES128|kCCKeySizeAES192|'
            b'kCCKeySizeAES256|kCCAlgorithmCAST|SecCertificateGetTypeID|'
            b'SecIdentityGetTypeID|SecKeyGetTypeID|SecPolicyGetTypeID|'
            b'SecTrustGetTypeID|SecCertificateCreateWithData|'
            b'SecCertificateCreateFromData|SecCertificateCopyData|'
            b'SecCertificateAddToKeychain|SecCertificateGetData|'
            b'SecCertificateCopySubjectSummary|SecIdentityCopyCertificate|'
            b'SecIdentityCopyPrivateKey|SecPKCS12Import|SecKeyGeneratePair|'
            b'SecKeyEncrypt|SecKeyDecrypt|SecKeyRawSign|SecKeyRawVerify|'
            b'SecKeyGetBlockSize|SecPolicyCopyProperties|'
            b'SecPolicyCreateBasicX509|SecPolicyCreateSSL|'
            b'SecTrustCopyCustomAnchorCertificates|SecTrustCopyExceptions|'
            b'SecTrustCopyProperties|SecTrustCopyPolicies|'
            b'SecTrustCopyPublicKey|SecTrustCreateWithCertificates|'
            b'SecTrustEvaluate|SecTrustEvaluateAsync|'
            b'SecTrustGetCertificateCount|SecTrustGetCertificateAtIndex|'
            b'SecTrustGetTrustResult|SecTrustGetVerifyTime|'
            b'SecTrustSetAnchorCertificates|SecTrustSetAnchorCertificatesOnly|'
            b'SecTrustSetExceptions|SecTrustSetPolicies|'
            b'SecTrustSetVerifyDate|SecCertificateRef|'
            b'SecIdentityRef|SecKeyRef|SecPolicyRef|SecTrustRef', dat)
        crypto_algo = list(set(crypto_algo))
        crypto_algo_s = b', '.join(crypto_algo)
        if len(crypto_algo_s) > 1:
            crypto = {
                'issue': 'Binary make use of the following Crypto API(s)',
                'status': 'Info',
                'description': ('The binary may use '
                                'the following crypto API(s) {}.').format(
                                    crypto_algo_s.decode('utf-8', 'ignore')),
                'cvss': 0,
                'cwe': ''}

        weak_hashes = {}
        weak_hash_algo = re.findall(
            b'CC_MD2_Init|CC_MD2_Update|CC_MD2_Final|CC_MD2|MD2_Init|'
            b'MD2_Update|MD2_Final|CC_MD4_Init|CC_MD4_Update|CC_MD4_Final|'
            b'CC_MD4|MD4_Init|MD4_Update|MD4_Final|CC_MD5_Init|CC_MD5_Update'
            b'|CC_MD5_Final|CC_MD5|MD5_Init|MD5_Update|MD5_Final|MD5Init|'
            b'MD5Update|MD5Final|CC_SHA1_Init|CC_SHA1_Update|'
            b'CC_SHA1_Final|CC_SHA1|SHA1_Init|SHA1_Update|SHA1_Final', dat)
        weak_hash_algo = list(set(weak_hash_algo))
        weak_hash_algo_s = b', '.join(weak_hash_algo)
        if len(weak_hash_algo_s) > 1:
            weak_hashes = {
                'issue': 'Binary make use of the following Weak HASH API(s)',
                'status': IN_SECURE,
                'description': (
                    'The binary may use the '
                    'following weak hash API(s) {}.').format(
                        weak_hash_algo_s.decode('utf-8', 'ignore')),
                'cvss': 3,
                'cwe': 'CWE-327'}

        hashes = {}
        hash_algo = re.findall(
            b'CC_SHA224_Init|CC_SHA224_Update|CC_SHA224_Final|CC_SHA224|'
            b'SHA224_Init|SHA224_Update|SHA224_Final|CC_SHA256_Init|'
            b'CC_SHA256_Update|CC_SHA256_Final|CC_SHA256|SHA256_Init|'
            b'SHA256_Update|SHA256_Final|CC_SHA384_Init|CC_SHA384_Update|'
            b'CC_SHA384_Final|CC_SHA384|SHA384_Init|SHA384_Update|'
            b'SHA384_Final|CC_SHA512_Init|CC_SHA512_Update|CC_SHA512_Final|'
            b'CC_SHA512|SHA512_Init|SHA512_Update|SHA512_Final', dat)
        hash_algo = list(set(hash_algo))
        hash_algo_s = b', '.join(hash_algo)
        if len(hash_algo_s) > 1:
            hashes = {
                'issue': 'Binary make use of the following HASH API(s)',
                'status': INFO,
                'description': ('The binary may use the'
                                ' following hash API(s) {}.').format(
                                    hash_algo_s.decode('utf-8', 'ignore')),
                'cvss': 0,
                'cwe': ''}

        randoms = {}
        rand_algo = re.findall(b'_srand|_random', dat)
        rand_algo = list(set(rand_algo))
        rand_algo_s = b', '.join(rand_algo)
        if len(rand_algo_s) > 1:
            randoms = {
                'issue': 'Binary make use of the insecure Random Function(s)',
                'status': IN_SECURE,
                'description': ('The binary may use the following '
                                'insecure Random Function(s) {}.').format(
                                    rand_algo_s.decode('utf-8', 'ignore')),
                'cvss': 3,
                'cwe': 'CWE-338'}

        logging = {}
        log = re.findall(b'_NSLog', dat)
        log = list(set(log))
        log_s = b', '.join(log)
        if len(log_s) > 1:
            logging = {
                'issue': 'Binary make use of Logging Function',
                'status': INFO,
                'description': ('The binary may use NSLog'
                                ' function for logging.'),
                'cvss': 7.5,
                'cwe': 'CWE-532'}

        malloc = {}
        mal = re.findall(b'_malloc', dat)
        mal = list(set(mal))
        mal_s = b', '.join(mal)
        if len(mal_s) > 1:
            malloc = {
                'issue': 'Binary make use of malloc Function',
                'status': IN_SECURE,
                'description': ('The binary may use malloc'
                                ' function instead of calloc.'),
                'cvss': 2,
                'cwe': 'CWE-789'}

        debug = {}
        ptrace = re.findall(b'_ptrace', dat)
        ptrace = list(set(ptrace))
        ptrace_s = b', '.join(ptrace)
        if len(ptrace_s) > 1:
            debug = {
                'issue': 'Binary calls ptrace Function for anti-debugging.',
                'status': WARNING,
                'description': ('The binary may use ptrace function. It can be'
                                ' used to detect and prevent debuggers.'
                                'Ptrace is not a public API and Apps that use'
                                ' non-public APIs will be rejected'
                                ' from AppStore.'),
                'cvss': 0,
                'cwe': ''}
        otool_dict['anal'] = [pie_flag,
                              ssmash,
                              arc_flag,
                              banned_apis,
                              weak_cryptos,
                              crypto,
                              weak_hashes,
                              hashes,
                              randoms,
                              logging,
                              malloc,
                              debug]
        return otool_dict
    except Exception:
        logger.exception('Performing Object Analysis of Binary')


def detect_bin_type(libs):
    """Detect IPA binary type."""
    if any('libswiftCore.dylib' in itm for itm in libs):
        return 'Swift'
    else:
        return 'Objective C'


def class_dump(tools_dir, bin_path, app_dir, bin_type):
    """Running Classdumpz on binary."""
    try:
        webview = {}
        if platform.system() == 'Darwin':
            logger.info('Dumping classes')
            if bin_type == 'Swift':
                logger.info('Running class-dump-swift aganst binary')
                if (len(settings.CLASSDUMP_SWIFT_BINARY) > 0
                        and is_file_exists(settings.CLASSDUMP_SWIFT_BINARY)):
                    class_dump_bin = settings.CLASSDUMP_SWIFT_BINARY
                else:
                    class_dump_bin = os.path.join(
                        tools_dir, 'class-dump-swift')
            else:
                logger.info('Running class-dump-z aganst binary')
                if (len(settings.CLASSDUMPZ_BINARY) > 0
                        and is_file_exists(settings.CLASSDUMPZ_BINARY)):
                    class_dump_bin = settings.CLASSDUMPZ_BINARY
                else:
                    class_dump_bin = os.path.join(tools_dir, 'class-dump-z')
            os.chmod(class_dump_bin, 0o777)
            args = [class_dump_bin, bin_path]
        elif platform.system() == 'Linux':
            logger.info('Running jtool against the binary for dumping classes')
            if (len(settings.JTOOL_BINARY) > 0
                    and is_file_exists(settings.JTOOL_BINARY)):
                jtool_bin = settings.JTOOL_BINARY
            else:
                jtool_bin = os.path.join(tools_dir, 'jtool.ELF64')
            os.chmod(jtool_bin, 0o777)
            args = [jtool_bin, '-arch', 'arm', '-d', 'objc', '-v', bin_path]
        else:
            # Platform not supported
            logger.warning('class-dump is not supported in this platform')
            return {}
        with open(os.devnull, 'w') as devnull:
            classdump = subprocess.check_output(args, stderr=devnull)
        if b'Source: (null)' in classdump and platform.system() == 'Darwin':
            logger.info('Running fail safe class-dump-swift')
            class_dump_bin = os.path.join(
                tools_dir, 'class-dump-swift')
            args = [class_dump_bin, bin_path]
            classdump = subprocess.check_output(args)
        dump_file = os.path.join(app_dir, 'classdump.txt')
        with open(dump_file, 'w') as flip:
            flip.write(classdump.decode('utf-8', 'ignore'))
        if b'UIWebView' in classdump:
            webview = {'issue': 'Binary uses WebView Component.',
                       'status': INFO,
                       'description': 'The binary may use WebView Component.',
                       'cvss': 0,
                       'cwe': '',
                       }
        return webview
    except Exception:
        logger.error('class-dump-z/class-dump-swift failed on this binary')


def strings_on_ipa(bin_path):
    """Extract Strings from IPA."""
    try:
        logger.info('Running strings against the Binary')
        unique_str = []
        unique_str = list(set(strings_util(bin_path)))  # Make unique
        unique_str = [escape(ip_str)
                      for ip_str in unique_str]  # Escape evil strings
        return unique_str
    except Exception:
        logger.exception('Running strings against the Binary')


def get_bin_info(bin_file):
    """Get Binary Information."""
    logger.info('Getting Binary Information')
    m = MachO(bin_file)
    for header in m.headers:
        if header.MH_MAGIC == MH_MAGIC_64 or header.MH_MAGIC == MH_CIGAM_64:
            sz = '64-bit'
        else:
            sz = '32-bit'
        arch = CPU_TYPE_NAMES.get(
            header.header.cputype, header.header.cputype)
        subarch = get_cpu_subtype(
            header.header.cputype, header.header.cpusubtype)
        return {'endian': header.endian,
                'bit': sz,
                'arch': arch,
                'subarch': subarch}


def binary_analysis(src, tools_dir, app_dir, executable_name):
    """Binary Analysis of IPA."""
    try:
        binary_analysis_dict = {}
        logger.info('Starting Binary Analysis')
        dirs = os.listdir(src)
        dot_app_dir = ''
        for dir_ in dirs:
            if dir_.endswith('.app'):
                dot_app_dir = dir_
                break
        # Bin Dir - Dir/Payload/x.app/
        bin_dir = os.path.join(src, dot_app_dir)
        if executable_name is None:
            bin_name = dot_app_dir.replace('.app', '')
        else:
            bin_name = executable_name
        # Bin Path - Dir/Payload/x.app/x
        bin_path = os.path.join(bin_dir, bin_name)
        binary_analysis_dict['libs'] = []
        binary_analysis_dict['bin_res'] = []
        binary_analysis_dict['strings'] = []
        if not is_file_exists(bin_path):
            logger.warning('MobSF Cannot find binary in %s', bin_path)
            logger.warning('Skipping Otool, Classdump and Strings')
        else:
            bin_info = get_bin_info(bin_path)
            otool_dict = otool_analysis(tools_dir, bin_name, bin_path, bin_dir)
            bin_type = detect_bin_type(otool_dict['libs'])
            cls_dump = class_dump(tools_dir, bin_path, app_dir, bin_type)
            if not cls_dump:
                cls_dump = {}
            strings_in_ipa = strings_on_ipa(bin_path)
            otool_dict['anal'] = list(
                filter(None, otool_dict['anal'] + [cls_dump]))
            binary_analysis_dict['libs'] = otool_dict['libs']
            binary_analysis_dict['bin_res'] = otool_dict['anal']
            binary_analysis_dict['strings'] = strings_in_ipa
            binary_analysis_dict['macho'] = bin_info
            binary_analysis_dict['bin_type'] = bin_type

        return binary_analysis_dict
    except Exception:
        logger.exception('iOS Binary Analysis')
