import { Component, ErrorInfo, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("AudioScoreTool UI error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="fatal-screen">
        <section className="fatal-card" role="alert">
          <div className="fatal-mark">!</div>
          <span className="page-eyebrow">APPLICATION ERROR</span>
          <h1>화면을 정상적으로 표시하지 못했습니다</h1>
          <p>작업 데이터는 로컬에 저장되어 있습니다. 앱을 다시 불러온 뒤에도 문제가 계속되면 아래 오류 내용을 확인하세요.</p>
          <details>
            <summary>오류 정보</summary>
            <pre>{this.state.error.message}</pre>
          </details>
          <div className="fatal-actions">
            <button className="secondary-button" onClick={() => this.setState({ error: null })}>화면 다시 시도</button>
            <button className="primary-button" onClick={() => window.location.reload()}>앱 다시 불러오기</button>
          </div>
        </section>
      </main>
    );
  }
}
