import projectLicense from "../../LICENSE?raw";
import projectNotice from "../../NOTICE?raw";
import "./legal-notices.css";

/** The original release notices are bundled by Vite, so this panel works offline. */
export default function LegalNotices() {
  return (
    <section className="work-card legal-notices-card" aria-labelledby="legal-notices-title">
      <div>
        <span className="card-kicker">OPEN SOURCE</span>
        <h3 id="legal-notices-title">라이선스 및 출처 표시</h3>
        <p>
          AudioScoreTool은 Apache License 2.0에 따라 상업적 이용이 가능합니다.
          소프트웨어를 재배포할 때는 해당 라이선스와 원저작물 출처 고지를 보존해야 합니다.
          아래 원문은 인터넷에 연결되지 않아도 확인할 수 있습니다.
        </p>
      </div>
      <div className="legal-notices-documents">
        <details>
          <summary>프로젝트 출처 고지 (NOTICE)</summary>
          <pre>{projectNotice}</pre>
        </details>
        <details>
          <summary>Apache License 2.0 전문</summary>
          <pre>{projectLicense}</pre>
        </details>
      </div>
      <p className="legal-notices-footnote">
        제3자 라이브러리와 모델의 배포·상업 이용 조건은 각자의 라이선스를 따릅니다.
        이 고지는 별도 화면 크레딧 의무를 추가하지 않습니다.
      </p>
    </section>
  );
}
