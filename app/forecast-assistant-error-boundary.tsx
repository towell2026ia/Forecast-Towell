"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

export default class ForecastAssistantErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    void _error;
    void _info;
    console.error("[ForecastAssistant]", { event: "ui_error" });
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
