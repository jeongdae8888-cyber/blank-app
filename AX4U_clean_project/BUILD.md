# Build Guide

## Local EXE Build

```powershell
pip install -r requirements.txt
pyinstaller --noconfirm --clean --windowed --name "AX4U_교통사고_영상분석기" --paths src src/ax4u/main.py
```

빌드 결과는 `dist/AX4U_교통사고_영상분석기/`에 생성됩니다. GitHub Actions는 배포 편의를 위해 아래 단일 파일 EXE 방식을 사용합니다.

## Single File EXE

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name "AX4U_교통사고_영상분석기" --paths src src/ax4u/main.py
```

## Installer

GitHub Actions에서는 PyInstaller 결과물을 `AX4U-Windows-EXE` artifact로 업로드합니다. Inno Setup이 설치된 환경에서는 `installer/AX4U_Setup.iss`를 사용해 `AX4U_Setup.exe`를 만들 수 있습니다.
