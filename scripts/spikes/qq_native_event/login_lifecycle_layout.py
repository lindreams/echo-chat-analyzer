"""Pinned disk-only login-listener ABI check. Never opens a QQ process."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile

from identity_layout_check import inspect

# Native listener entries before asynchronous JS dispatch. Success takes an
# object pointer; only its uint64 UIN at +0x30 is observed. State is int32.
# Static ABI evidence does not attest runtime login/lifecycle semantics.
POINTS = (
    ('Success', 8, 0x22a9cc8, 0x22a9d5c, 0x22acc31, 0x22acd7e, b'onQRCodeLoginSucceed', b'\x48\x89\x48\xf8'),
    ('State', 7, 0x22a9bfa, 0x22a9c80, 0x22ac86d, 0x22ac9c5, b'onLoginState', b'\x89\x50\x18'),
    ('Logout', 11, 0x22aa106, 0x22aa17d, 0x22add19, 0x22ade4c, b'onLogoutSucceed', b'\x48\x89\x4a\x10'),
    ('Disconnected', 2, 0x22a97be, 0x22a9835, 0x22ab573, 0x22ab6a0, b'onLoginDisConnected', b'\x48\x89\x4a\x10'),
    ('Connecting', 3, 0x22a9876, 0x22a98ed, 0x22ab8ad, 0x22ab9da, b'onLoginConnecting', b'\x48\x89\x4a\x10'),
    ('Connected', 1, 0x22a9706, 0x22a977d, 0x22ab239, 0x22ab366, b'onLoginConnected', b'\x48\x89\x4a\x10'),
)
VTABLE = 0x4436218


def verify():
    module, base, _ = inspect()  # Existing version/hash and send ABI check.
    pe = pefile.PE(str(module), fast_load=True)
    image = pe.get_memory_mapped_image()
    entry = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    functions = {(a, b) for a, b, _ in struct.iter_unpack('<III', pe.get_data(entry.VirtualAddress, entry.Size))}
    # Complete-object locator -> type descriptor, not a guessed table ordering.
    locator = struct.unpack_from('<Q', image, VTABLE-8)[0]-base
    signature, offset, _, descriptor, _, self_rva = struct.unpack_from('<6I', image, locator)
    name = b'.?AVNodeIKernelLoginListener@@\0'
    if (signature, offset, self_rva) != (1, 0, locator) or image[descriptor+16:descriptor+16+len(name)] != name:
        raise ValueError('listener_type_unconfirmed')
    records = []
    for label, slot, begin, end, proxy, proxy_end, event, flow in POINTS:
        if ((begin, end) not in functions or (proxy, proxy_end) not in functions
                or struct.unpack_from('<Q', image, VTABLE+slot*8)[0] != base+begin
                or image[begin:end].count(flow) != 1):
            raise ValueError('listener_abi_unconfirmed')
        refs = set()
        for at in range(proxy, proxy_end-6):
            if image[at]&0xf8 != 0x48 or image[at+1] != 0x8d or image[at+2]&0xc7 != 5:
                continue
            dest = at+7+struct.unpack_from('<i', image, at+3)[0]
            if 0 <= dest < len(image):
                refs.add(image[dest:image.find(b'\0', dest, dest+160)])
        if event not in refs or not any(b'NodeIKernelLoginListener.cpp' in item for item in refs):
            raise ValueError('listener_callback_unconfirmed')
        records.append({'name': label, 'begin': begin, 'end': end,
                        'prefix': image[begin:begin+32].hex(),
                        'sha256': hashlib.sha256(image[begin:end]).hexdigest()})
    pe.close()
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--header', type=Path)
    args = parser.parse_args()
    try:
        records = verify()
        if args.header:
            root = Path(__file__).resolve().parents[3]/'build'
            if not args.header.resolve().is_relative_to(root):
                raise ValueError('isolated_build_required')
            rows = []
            for item in records:
                prefix = ','.join('0x'+item['prefix'][at:at+2] for at in range(0, 64, 2))
                rows.append('{0x%x,0x%x,{%s},"%s","EchoFixture%s"}' %
                            (item['begin'], item['end'], prefix, item['sha256'], item['name']))
            args.header.write_text('constexpr LoginPoint login_points[] = {\n'+',\n'.join(rows)+'\n};\n', encoding='ascii')
        print(json.dumps({'pinned_listener_abi': True, 'observation_points': len(records),
                          'qq_process_accessed': False, 'runtime_identity_proven': False}))
    except Exception as error:
        allowed = {'listener_type_unconfirmed', 'listener_abi_unconfirmed',
                   'listener_callback_unconfirmed', 'isolated_build_required'}
        print(json.dumps({'pinned_listener_abi': False,
                          'reason': str(error) if str(error) in allowed else 'listener_layout_refused'}))
        raise SystemExit(1)
