# QQ NT 市场表情包提取工具

把自己在 QQ 聊天中**已经收到**的市场表情包（marketface）还原成可直接使用的 GIF，
或从官方公开 CDN 取回同一表情的 300×300 版本，便于个人备份和格式转换。

## 免责声明

- 本工具仅用于**备份自己账号中已经收到的表情**，以及了解其文件存储格式。
- 不涉及、不提供任何绕过付费、授权、会员或版权保护的功能；未收到的内容本工具无法获取。
- 表情的著作权归原作者与平台所有。请勿将提取结果用于商业用途、二次分发或冒充原创。
- 使用本工具可能违反相关平台的服务条款，是否使用由你自行判断并承担全部后果。
- 若权利人认为本项目不妥，请提交 issue，会及时处理。

## 原理

QQ NT 将收到的商城表情缓存在：

```
<QQ数据目录>/nt_qq/nt_data/Emoji/marketface/<表情包ID>/
```

每个表情通常有两份文件，共用同一个资源 ID 作为文件名：

| 文件 | 内容 | 说明 |
| --- | --- | --- |
| `<id>_aio.png` | 200×200 RGBA PNG | 聊天窗口渲染用的预览图，未做混淆 |
| `<id>` | GIF（无扩展名） | 实际表情，按下面的规则做了分段异或 |

混淆规则（实测）：

```
每 50 字节为一个周期，从头开始
    前 20 字节 ^ 0xFF
    后 30 字节保持原样
末尾不足一个周期的部分按同样规则处理
```

解开后就是标准 GIF。部分旧版本使用相反的 `30 异或 / 20 原样`，脚本会自动回退尝试。

## 更高的分辨率

本地缓存的 GIF 只有 200×200（客户端渲染用），**300×300 的原始规格不在本地**。
资源 ID 不是文件内容的哈希，因此可以按下面的公开地址取回 300 规格：

```
https://gxh.vip.qq.com/club/item/parcel/item/<ID前2位>/<ID>/raw300.gif
https://gxh.vip.qq.com/club/item/parcel/item/<ID前2位>/<ID>/300x300.png
```

`--cdn` 参数即使用这条路径；400/500/600 等尺寸不存在。

## 用法

需要 Python 3.10+，校验功能可选依赖 Pillow：

```bash
pip install pillow          # 可选，仅 --verify 需要
```

```bash
# 自动查找本机 QQ 缓存，解密到 ./out
python decrypt_marketface.py

# 指定输入目录
python decrypt_marketface.py -i "C:/Users/you/Documents/Tencent Files/<QQ号>/nt_qq/nt_data/Emoji/marketface"

# 取 300x300 官方规格（失败自动回退本地解密），8 线程
python decrypt_marketface.py -i <目录> --cdn -w 8

# 同时导出预览图，并校验解码结果
python decrypt_marketface.py -i <目录> --with-aio --verify
```

输出文件名格式为 `<表情包ID>_<资源ID>.gif`，`--cdn` 时为 `..._300.gif`，避免不同表情包重名。

## 参数

| 参数 | 说明 |
| --- | --- |
| `-i, --input` | 输入文件或目录，默认自动探测本机 QQ 缓存 |
| `-o, --output` | 输出目录，默认脚本旁的 `out/` |
| `--cdn` | 优先从公开 CDN 取 300×300，失败回退本地解密 |
| `-w, --workers` | 并发线程数，默认 6 |
| `--with-aio` | 同时导出未加密的 `_aio.png` |
| `--verify` | 用 Pillow 校验并打印尺寸与帧数 |
| `--quiet` | 只输出汇总 |

## 兼容性

- 在 QQ NT（Windows）实测通过，`marketface` 目录下 996 个本体全部解密成功。
- 段长、目录结构可能随版本变化；如果全部失败，可先确认文件开头按前 20 字节异或后
  是否为 `GIF89a`，据此判断实际分段方式。
- 脚本不修改任何 QQ 数据，只读取并输出到独立目录。

## License

[MIT](LICENSE)
