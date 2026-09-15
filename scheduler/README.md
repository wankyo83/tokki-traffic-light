# 중앙신호등 GitHub 검사 보조 스케줄러

GitHub Actions의 예약 실행이 늦거나 누락될 때만 `pages.yml`의 `workflow_dispatch`를 호출하는 Cloudflare Worker입니다.

- 5분마다 공개 `status.json`의 `checkedAt`을 확인합니다.
- 마지막 GitHub 검사가 12분 이상 지났거나 상태 파일을 읽지 못했을 때만 실행을 요청합니다.
- GitHub 기본 예약 실행은 그대로 유지하므로 어느 한쪽이 중단돼도 다른 쪽이 남습니다.
- `/health`에서 마지막 공개 검사 시각과 실행 필요 여부를 확인할 수 있습니다.

배포 전, 이 저장소의 Actions만 실행할 수 있는 별도 GitHub fine-grained token을 Worker secret으로 등록합니다.

```powershell
npx wrangler secret put GITHUB_ACTIONS_TOKEN
npx wrangler deploy
```

토큰은 `wankyo83/tokki-traffic-light` 저장소 한 곳에만 접근할 수 있게 제한하고 Actions `Read and write` 권한만 부여합니다.
