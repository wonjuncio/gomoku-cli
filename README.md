# gomoku-cli

CLI 버전 오목 게임 (15x15, 5목 승리)

## 사용법

### 호스트 (서버)
```bash
python gomoku.py host --port 33333
```

### 게스트 (참가)
```bash
python gomoku.py join --host <HOST_IP> --port 33333 --name Guest
```

## 조작법

### 수 입력
- 좌표 형식: `8 8` (x y)
- 체스 형식: `H8` (알파벳 A-O + 숫자 1-15)

### 명령어
- `/help` - 도움말
- `/swap` - 게임 시작 전에만 사용 가능, 흑백 순서 바꾸기
- `/restart` - 게임 재시작 (상대방 확인 필요)
- `/undo` - 한 수 취소 (상대방 확인 필요)
- `/quit` - 게임 종료

**참고:** 선공은 O, 후공은 X입니다.

## Contributing

버그 리포트나 기능 제안은 [Issues](https://github.com/wonjuncio/gomoku-cli/issues)에 등록해 주세요. Pull Request도 환영합니다.