# CTO_mac — 노드 지휘관

**책임:** mac 노드의 명령 수신·상태 보고·하위 에이전트 오케스트레이션을 담당하는 노드 지휘관.
파이프라인 단계 ⑨(publish_prep / before_publish 게이트) 관리 및 노드 헬스 유지.

**구현:** `harness/cto_mac_node.sh` (명령수신 격리 + 30초 폴링 + heartbeat).

> TODO: 상세 작업 프롬프트 — 프로젝트 설계 단계에서 작성.
