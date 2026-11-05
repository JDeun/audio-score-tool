# main 브랜치 보호 정책 — 운영 활성화 절차 (#38)

## 현재 상태 및 권한

2026-11-05 확인: 저장소 ruleset 목록은 **비어 있음**. GitHub 연동 권한으로 `branches/main/protection`을 읽으려 하면 HTTP 403이 발생하므로, **기존 branch protection이 실제로 없는지까지는 이 권한으로 단정할 수 없습니다**.

코드 검사기와 승인 기준을 추가하는 것과 저장소에 보호 규칙을 **실제로 설정하는 것**은 구분합니다. 후자는 저장소 `Administration` 권한 보유자가 GitHub 설정에서 적용해야 합니다. 이 저장소의 CI 체크런 이름은 API에서 `verify`로 확인되며 워크플로 이름은 `CI`입니다.

## main 필수 보호 계약

- `main` 변경은 PR을 통해서만 허용합니다. 기존 작업 방식에 맞춰 승인 리뷰 최소 수는 저장소 관리자가 결정하되, PR 요구 자체는 비활성화하지 않습니다.
- `verify` GitHub Actions 체크가 성공해야 합니다. **Strict / require branches to be up to date**를 사용하거나 검증된 merge queue를 별도로 운영합니다.
- force push/비정상 히스토리 변경을 차단합니다.
- 브랜치 삭제를 차단합니다.
- 우회 가능한 계정·앱·관리자 정책을 명시하고 감사합니다. 기본값은 무우회입니다.
- release 태그 발행/서명 권한은 #22에서 별도로 처리합니다.

## GitHub 관리자 작업

Repository → Settings → Rules → Rulesets에서 `main`을 대상으로 한 **활성화된 branch ruleset**을 만듭니다. Rule 목록에 Require pull request, Require status checks (`verify`, GitHub Actions에서 발행), Block force pushes, Restrict deletions를 설정합니다. Strict status checks를 적용하고, 우회 허용 사용자는 의도적으로 검토합니다.

또는 Settings → Branches에서 전통적인 branch protection을 사용해 동등한 규칙을 설정합니다. 실제 저장소에서 보호 설정이 없으면 PR의 CI 성공만으로 direct push를 막을 수 없습니다.

관리자 권한으로 정책을 적용한 뒤, **읽기 전용** API 스냅샷을 작업 디렉터리 바깥에 저장합니다.

```bash
# 먼저 관리자 계정으로 gh auth login 수행
gh api repos/JDeun/audio-score-tool/rulesets
gh api repos/JDeun/audio-score-tool/rulesets/<RULESET_ID> > /tmp/ast-main-ruleset.json
uv run --frozen python scripts/audit_branch_governance.py \
  --ruleset /tmp/ast-main-ruleset.json

# 전통적인 branch protection 사용 시 대안:
gh api repos/JDeun/audio-score-tool/branches/main/protection \
  > /tmp/ast-main-protection.json
uv run --frozen python scripts/audit_branch_governance.py \
  --protection /tmp/ast-main-protection.json
```

검사기는 완전한 활성화 규칙이 확인되면 `protected: true`, 누락되거나 읽기 권한이 없으면 `protected: false` 및 **nonzero exit**를 반환합니다. 명령은 네트워크를 호출하거나 보호 규칙을 적용하지 않습니다. 정책 상태 스냅샷은 토큰이 아닌 공개 규칙 메타데이터만 포함해야 합니다.

## 인수시험

1. 동일 저장소의 격리된 테스트 브랜치에서 CI 실패를 발생시키고 `main`에 병합이 거부되는지 확인합니다.
2. 권한 제한된 일반 개발자로 `main` direct push가 거부되는지 확인합니다.
3. force push 및 브랜치 삭제가 거부되는지 확인합니다.
4. 정상적인 PR이 최신 `verify` 성공 후 병합 가능한지 확인합니다.

이 시험들은 관리 권한·실제 GitHub 설정이 필요합니다. 본 문서/검사기 추가만으로 이슈 #38을 완료했다고 표시하지 않습니다.
