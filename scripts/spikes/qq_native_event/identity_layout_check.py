"""Read only the public installed module; no process, config or account access."""
import json
from pathlib import Path
import struct
import pefile

from qq_chat_analyzer.application.qq.qq_auth_bridge import _qq_install_candidates
from qq_chat_analyzer.application.qq.qq_version import read_qq_resources
from identity_probe import MODULE_HASH, digest


def inspect():
    candidates = {p.resolve() for p in _qq_install_candidates() if p.is_file()}
    resources = [read_qq_resources(p) for p in candidates]
    resources = [r for r in resources if r is not None and r.version == (9, 9, 37, 54395)]
    if len(resources) != 1 or digest(resources[0].wrapper_path) != MODULE_HASH:
        raise ValueError('exact_module_required')
    pe = pefile.PE(str(resources[0].wrapper_path), fast_load=True)
    image = pe.get_memory_mapped_image()
    prefix = bytes.fromhex('55 41 57 41 56 41 55 41 54 56 57 53 48 81 ec 08 01 00 00 48 8d ac 24 80 00 00 00 48 c7 85 80 00')
    anchors = (b'InternalPushTask\0', b'MSF task pushed seq:{} uin:{} uin_type:{} cmd:{} data_size:{} custom_sig:{}\0')
    matches = []
    exception = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    entries = pe.get_data(exception.VirtualAddress, exception.Size)
    for begin, end, _ in struct.iter_unpack('<III', entries):
        if not 32 <= end-begin <= 65536 or image[begin:begin+32] != prefix:
            continue
        found = set()
        for i in range(begin, end-6):
            if image[i]&0xf8 != 0x48 or image[i+1] != 0x8d or image[i+2]&0xc7 != 5:
                continue
            destination = i+7+struct.unpack_from('<i', image, i+3)[0]
            for anchor in anchors:
                if destination >= 0 and image[destination:destination+len(anchor)] == anchor:
                    found.add(anchor)
        if len(found) == 2:
            matches.append((begin, end))
    if len(matches) != 1:
        raise ValueError('unique_send_function_required')
    begin, end = matches[0]
    function = image[begin:end]
    # Independent byte-level check of the native argument flow, after examining
    # MSVC's disassembly: task->[+0x50] -> edi -> log arg; task+0x38 -> string copy.
    # Still no assertion about any runtime value or a global enum definition.
    if function.count(bytes.fromhex('48 8b 13 8b 7a 50 48 83 c2 38')) != 1 or function.count(bytes.fromhex('89 7c 24 40')) != 1:
        raise ValueError('account_log_argument_flow_unconfirmed')
    return resources[0].wrapper_path, pe.OPTIONAL_HEADER.ImageBase, matches[0]


if __name__ == '__main__':
    try:
        _, _, (begin, end) = inspect()
        print(json.dumps({'pinned_module_matches': True, 'unique_send_function': True,
                          'begin_rva': hex(begin), 'end_rva': hex(end), 'runtime_account_evidence': False}))
    except (OSError, ValueError) as error:
        reason = str(error) if str(error) in ('exact_module_required', 'unique_send_function_required', 'account_log_argument_flow_unconfirmed') else 'layout_inspection_refused'
        print(json.dumps({'pinned_module_matches': False, 'runtime_account_evidence': False, 'reason': reason}))
        raise SystemExit(1)
