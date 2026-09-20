"use client";

import { useEffect, useRef } from "react";

export default function ForecastAssistantLottie({ onError }: { onError: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let animation: import("lottie-web").AnimationItem | undefined;

    void import("lottie-web/build/player/lottie_light")
      .then(({ default: lottie }) => {
        if (disposed || !containerRef.current) return;
        animation = lottie.loadAnimation({
          container: containerRef.current,
          renderer: "svg",
          loop: true,
          autoplay: true,
          path: "/lottie/forecast-assistant.json",
          rendererSettings: { preserveAspectRatio: "xMidYMid meet" },
        });
        animation.addEventListener("data_failed", onError);
        animation.addEventListener("error", onError);
      })
      .catch(onError);

    return () => {
      disposed = true;
      animation?.destroy();
    };
  }, [onError]);

  return <div ref={containerRef} className="size-full" aria-hidden="true" />;
}
