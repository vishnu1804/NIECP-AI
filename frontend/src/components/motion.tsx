/**
 * Micro-animation primitives (spec §47) — a tiny local stand-in for
 * framer-motion covering the transitions this app uses. Swap-in compatible:
 * replacing with framer-motion's AnimatePresence/motion keeps the same API.
 */
import React, { useEffect, useState } from "react";

export function AnimatePresence({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function motion({
  initial = {},
  animate = {},
  exit = {},
  transition,
  className,
  children,
  ...rest
}: any) {
  const [phase, setPhase] = useState<"enter" | "in" | "exit">("enter");
  useEffect(() => {
    const raf = requestAnimationFrame(() => setPhase("in"));
    return () => cancelAnimationFrame(raf);
  }, []);
  const style: React.CSSProperties = {
    ...rest.style,
    opacity: phase === "in" ? (animate.opacity ?? 1) : (initial.opacity ?? 1),
    transform: phase === "in" ? animate.scale ? `scale(${animate.scale})` : rest.style?.transform : initial.scale ? `scale(${initial.scale})` : rest.style?.transform,
    transition: `opacity ${(transition?.duration ?? 0.22)}s ease, transform ${(transition?.duration ?? 0.22)}s ease`,
  };
  return (
    <div className={className} style={style} {...rest}>
      {children}
    </div>
  );
}
