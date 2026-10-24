#!/usr/bin/env python3
"""mkvsix.py — the VS Code extension (vscode/) as one .vsix, without node or npm: a VSIX is a zip of extension/ (the
extension's files) with its manifest (extension.vsixmanifest) and [Content_Types].xml.

  mkvsix.py [--out out/wavelens-0.17.0.vsix] [--sva bin/linux-x86_64/sva] [--target linux-x64]

Into extension/: vscode/package.json (its "version" from VERSION: 0.17 -> 0.17.0), vscode/extension.js, vscode/media/
host.js, the viewer's files of wavelens/ under media/ (wavelens.css, wavelens.config.js, wavelens.js, sva.wasm.js, bus.js,
sva.js), the static sva CLI as bin/sva (mode 755; FST -> VCD text on the host), vscode/README.md. The
package is for one platform of the host that runs the extension (Remote-SSH / WSL: the Linux machine): --target.
The same input gives the same bytes (fixed times in the zip). Install: code --install-extension FILE.vsix in a terminal
of the remote window, or Extensions → … → Install from VSIX… while connected.
"""
import argparse, json, os, sys, zipfile
from xml.sax.saxutils import escape

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import WaveError, run_main  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = ['wavelens.css', 'wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js']
TYPES = {'.json': 'application/json', '.js': 'application/javascript', '.css': 'text/css', '.md': 'text/markdown',
         '.txt': 'text/plain', '.vsixmanifest': 'text/xml'}


def manifest(pkg, target):
    """extension.vsixmanifest from package.json."""
    e = lambda s: escape(str(s), {'"': '&quot;'})
    props = {
        'Microsoft.VisualStudio.Code.Engine': pkg['engines']['vscode'],
        'Microsoft.VisualStudio.Code.ExtensionDependencies': '',
        'Microsoft.VisualStudio.Code.ExtensionPack': '',
        'Microsoft.VisualStudio.Code.ExtensionKind': ','.join(pkg.get('extensionKind', ['workspace'])),
        'Microsoft.VisualStudio.Code.LocalizedLanguages': '',
    }
    return f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{e(pkg['name'])}" Version="{e(pkg['version'])}" Publisher="{e(pkg['publisher'])}"{f' TargetPlatform="{e(target)}"' if target else ''} />
    <DisplayName>{e(pkg['displayName'])}</DisplayName>
    <Description xml:space="preserve">{e(pkg['description'])}</Description>
    <Tags>{e(','.join(pkg.get('keywords', [])))}</Tags>
    <Categories>{e(','.join(pkg.get('categories', [])))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
{chr(10).join(f'      <Property Id="{k}" Value="{e(v)}" />' for k, v in props.items())}
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />
  </Assets>
</PackageManifest>
'''


def content_types(names):
    exts = sorted({os.path.splitext(n)[1] for n in names if os.path.splitext(n)[1]})
    rows = [f'  <Default Extension="{x}" ContentType="{TYPES.get(x, "application/octet-stream")}" />' for x in exts]
    rows += [f'  <Override PartName="/{n}" ContentType="application/octet-stream" />' for n in names if not os.path.splitext(n)[1]]
    return ('<?xml version="1.0" encoding="utf-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            + '\n'.join(rows) + '\n</Types>\n')


def build(out, sva, target):
    with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
        ver = f.read().strip()
    with open(os.path.join(ROOT, 'vscode', 'package.json'), encoding='utf-8') as f:
        pkg = json.load(f)
    pkg['version'] = ver + '.0' * (2 - ver.count('.'))   # semver: 0.17 -> 0.17.0
    b = common.build_info('VSIX')   # the bar's version line in the tab: the commit it was packed from (no git where it runs)
    if b:
        pkg['wavelensBuild'] = b
    files = [('extension/package.json', json.dumps(pkg, indent=2, ensure_ascii=False).encode() + b'\n', 0o644)]
    src = [('extension.js', 'vscode/extension.js'), ('svtypes.js', 'vscode/svtypes.js'), ('media/host.js', 'vscode/media/host.js'), ('README.md', 'vscode/README.md')] + [('media/' + m, 'wavelens/' + m) for m in MEDIA]
    for name, p in src:
        with open(os.path.join(ROOT, p), 'rb') as f:
            files.append(('extension/' + name, f.read(), 0o644))
    if not os.path.isfile(sva):
        raise WaveError(f'no sva CLI at {sva} (make dist-linux, or --sva)')
    with open(sva, 'rb') as f:
        files.append(('extension/bin/sva', f.read(), 0o755))
    names = [n for n, _, _ in files]
    head = [('[Content_Types].xml', content_types(names + ['extension.vsixmanifest']).encode(), 0o644),
            ('extension.vsixmanifest', manifest(pkg, target).encode(), 0o644)]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + '.part'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in head + files:
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.create_system, zi.external_attr, zi.compress_type = 3, (0o100000 | mode) << 16, zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    os.replace(tmp, out)
    return pkg['version'], len(names)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split('\n\n', 1)[1])
    ap.add_argument('--out', help='the .vsix (default: out/wavelens-VERSION.vsix)')
    ap.add_argument('--sva', default=os.path.join(ROOT, 'bin', 'linux-x86_64', 'sva'), help='the static sva CLI of the host (default: %(default)s)')
    ap.add_argument('--target', default='linux-x64', help='the platform of the host, as VS Code names it (default: %(default)s; "" none)')
    a = ap.parse_args()
    with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
        ver = f.read().strip()
    out = a.out or os.path.join(ROOT, 'out', f'wavelens-{ver}.0.vsix')
    v, n = build(out, a.sva, a.target)
    print(f'mkvsix: {out} (wavelens {v}, {n} files, {os.path.getsize(out) // 1024} KB)')


if __name__ == '__main__':
    run_main(main, 'mkvsix')
