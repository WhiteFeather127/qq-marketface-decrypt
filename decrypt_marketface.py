#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QQ NT 市场表情包（marketface）提取工具。

两种取图方式
------------
1. 本地解密（默认）：把 QQ 缓存的加密本体还原成可用的 GIF。
   QQ 缓存位置：
       <QQ数据目录>/nt_qq/nt_data/Emoji/marketface/<表情包ID>/
   每个表情两份文件：
       <md5>_aio.png   预览图，未加密，200x200，可直接打开
       <md5>           本体，分段异或混淆后的 GIF，200x200

2. 腾讯 CDN 高清版（--cdn）：文件名就是资源 md5，可以直接拼出原始资源地址，
   拿到 300x300 的版本（比本地缓存大一档）：
       https://gxh.vip.qq.com/club/item/parcel/item/<md5前2位>/<md5>/raw300.gif
       https://gxh.vip.qq.com/club/item/parcel/item/<md5前2位>/<md5>/300x300.png

混淆规则（本机 QQ 版本实测）
--------------------------
以 50 字节为一个周期，从头开始：
    前 20 字节 ^ 0xFF
    后 30 字节保持原样
末尾不足一个周期的部分按同样规则处理。
部分旧版本是相反的 30 异或 / 20 原样，脚本会自动回退尝试。

用法
----
    python decrypt_marketface.py                     # 自动扫描本机缓存，输出到 ./out
    python decrypt_marketface.py -i <目录或文件>      # 指定输入
    python decrypt_marketface.py -i <目录> --cdn      # 改为从 CDN 下 300x300 高清版
    python decrypt_marketface.py -i <目录> --cdn -w 8 # 8 线程并发下载
    python decrypt_marketface.py -i <目录> --with-aio --verify
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

XOR_KEY = 0xFF
PRIMARY = (20, 30)   # (异或字节数, 原样字节数)
FALLBACK = (30, 20)

CDN_URL = "https://gxh.vip.qq.com/club/item/parcel/item/{prefix}/{md5}/{name}"
CDN_NAMES = ("raw300.gif", "300x300.png")

MAGICS = (
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"BM", "bmp"),
)


def detect_type(data: bytes) -> str | None:
    """按文件魔数判断真实格式。"""
    for magic, ext in MAGICS:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def unmask(data: bytes, xor_len: int, plain_len: int) -> bytes:
    """按周期把前 xor_len 字节与 0xFF 异或，后 plain_len 字节保持原样。"""
    period = xor_len + plain_len
    out = bytearray(data)
    for i in range(len(out)):
        if i % period < xor_len:
            out[i] ^= XOR_KEY
    return bytes(out)


def decrypt(data: bytes) -> tuple[bytes | None, str | None, tuple[int, int] | None]:
    """尝试两种分段顺序，返回 (明文, 扩展名, 采用的分段参数)。"""
    for combo in (PRIMARY, FALLBACK):
        out = unmask(data, *combo)
        ext = detect_type(out)
        if ext:
            return out, ext, combo
    return None, None, None


def is_md5(name: str) -> bool:
    return len(name) == 32 and all(c in "0123456789abcdef" for c in name.lower())


def fetch_cdn(md5: str, timeout: int = 12) -> tuple[bytes | None, str | None, str | None]:
    """从腾讯 CDN 取 300x300 原始资源，返回 (数据, 扩展名, 使用的文件名)。"""
    url_base = CDN_URL.format(prefix=md5[:2].lower(), md5=md5.lower(), name="")
    for name in CDN_NAMES:
        url = url_base + name
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        ext = detect_type(data)
        if data and ext:
            return data, ext, name
    return None, None, None


def verify_image(data: bytes) -> str:
    """用 Pillow 校验（可选依赖），返回描述信息；失败返回原因。"""
    try:
        import io

        from PIL import Image
    except ImportError:
        return "跳过（未安装 Pillow）"
    try:
        im = Image.open(io.BytesIO(data))
        return f"{im.format} {im.size[0]}x{im.size[1]} {getattr(im, 'n_frames', 1)}帧"
    except Exception as exc:  # noqa: BLE001
        return f"解码失败: {exc}"


def default_input() -> Path | None:
    """在本机常见的 QQ 数据目录里找工作表情缓存目录。"""
    home = Path.home()
    roots = [
        home / "Documents" / "Tencent Files",
        home / "Documents" / "Tencent Files" / "Tencent Files",
        home / "AppData" / "Roaming" / "Tencent",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.glob("*/nt_qq/nt_data/Emoji/marketface"):
            if candidate.is_dir():
                return candidate
    return None


def iter_targets(src: Path):
    """产出待处理的本体文件（跳过 _aio.png 之类的缩略图与元数据）。"""
    if src.is_file():
        yield src
        return
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".json", ".tmp"}:
            continue
        yield p


def handle_one(path: Path, out_dir: Path, args) -> tuple[bool, str]:
    """处理单个文件，返回 (是否成功, 说明)。"""
    stem = f"{path.parent.name}_{path.name}" if args._root_is_dir else path.stem

    if args.cdn and is_md5(path.name):
        data, ext, used = fetch_cdn(path.name)
        if data:
            target = out_dir / f"{stem}_300.{ext}"
            target.write_bytes(data)
            extra = f"  {verify_image(data)}" if args.verify else ""
            return True, f"[CDN] {path.name} -> {target.name} ({used}){extra}"

    raw = path.read_bytes()
    plain, ext, combo = decrypt(raw)
    if plain is None:
        return False, f"[跳过] {path.name} 无法识别（可能不是表情本体）"

    target = out_dir / f"{stem}.{ext}"
    target.write_bytes(plain)
    if args.with_aio:
        aio = path.with_name(path.name + "_aio.png")
        if aio.is_file():
            (out_dir / f"{stem}_aio.png").write_bytes(aio.read_bytes())

    order = "20异或/30原样" if combo == PRIMARY else "30异或/20原样"
    extra = f"  {verify_image(plain)}" if args.verify else ""
    prefix = "[本地]" if args.cdn else "[OK]"
    return True, f"{prefix} {path.name} -> {target.name}  ({order}){extra}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="解密 / 下载 QQ NT 市场表情包本体",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-i", "--input", help="输入文件或目录（默认自动查找本机 QQ 缓存）")
    ap.add_argument("-o", "--output", help="输出目录（默认脚本旁的 out/）")
    ap.add_argument("--cdn", action="store_true", help="优先从腾讯 CDN 下载 300x300 高清版，失败回退本地解密")
    ap.add_argument("-w", "--workers", type=int, default=6, help="并发线程数（默认 6）")
    ap.add_argument("--with-aio", action="store_true", help="同时导出未加密的 _aio.png 缩略图")
    ap.add_argument("--verify", action="store_true", help="用 Pillow 校验结果并打印尺寸/帧数")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args(argv)

    if args.input:
        src = Path(args.input).expanduser()
    else:
        src = default_input()
        if src is None:
            print("未找到 QQ 表情缓存目录，请用 -i 指定路径", file=sys.stderr)
            return 2

    if not src.exists():
        print(f"路径不存在: {src}", file=sys.stderr)
        return 2

    out_dir = Path(args.output).expanduser() if args.output else Path(__file__).resolve().parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    args._root_is_dir = src.is_dir()

    targets = list(iter_targets(src))
    done = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for ok, msg in pool.map(lambda p: handle_one(p, out_dir, args), targets):
            if ok:
                done += 1
            else:
                failed += 1
            if not args.quiet:
                print(msg)

    print(f"\n完成：成功 {done} 个，跳过 {failed} 个，输出目录 {out_dir}")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
