# 朗读女 (Reader TTS)

基于百度语音合成的 TXT 朗读软件，PyQt5 + pygame。

## 打包 EXE

```
py -3 -m pip install --upgrade pyinstaller
py -3 -m PyInstaller build.spec --clean
```

产物：`dist/朗读女.exe`（单文件，~25MB）

## 运行依赖（开发环境）

```
pip install PyQt5 pygame requests
```

## 使用

1. 启动后 **选项 → 百度语音设置** 填入 API Key / Secret Key
2. 打开或粘贴 txt 文本
3. 点 ▶ 播放
