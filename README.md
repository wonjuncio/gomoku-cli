# gomoku-cli

CLI 버전 오목 게임 (15x15, 5목 승리)

<details>
<summary>비밀</summary>

UI가 부담스러워 몰래 하려 만든 gomoku😏

</details>

</details>

## 사용법

### 호스트 (서버)
```bash
python gomoku.py host --port 33333 [--renju/--no-renju]
```
- port (옵션, default: 33333)
- renju (옵션, default: True) - 렌주룰 적용 여부

### 게스트 (참가)
```bash
python gomoku.py join --host <HOST_IP> --port 33333 --name Guest
```
- host (호스트 ip, 필수)
- port (옵션, default: 33333)
- name (닉네임, 옵션, default: Guest)

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

## 렌주룰 (Renju Rules)

렌주룰이 활성화된 경우 (`--renju`, 기본값), 선공(O)에게 다음 제한이 적용됩니다:

- **정확히 5목 승리**: 6목 이상은 금지 (장목 금지)
- **33 금지**: 열린 3이 2개 이상인 수는 금지
- **44 금지**: 열린 4가 2개 이상인 수는 금지

금지된 수를 놓으려고 하면 알림이 표시되고 해당 수는 무효화됩니다. 후공(X)에게는 렌주룰이 적용되지 않습니다.

렌주룰을 비활성화하려면 `--no-renju` 옵션을 사용하세요.

## Contributing

버그 리포트나 기능 제안은 [Issues](https://github.com/wonjuncio/gomoku-cli/issues)에 등록해 주세요. Pull Request도 환영합니다.