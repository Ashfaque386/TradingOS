"use client";

import { motion, useSpring, useTransform } from "framer-motion";
import { useEffect } from "react";

/** Rolling "odometer" number animation per Phase_7_Frontend_Architecture.md §1.3, so PnL swings
 * read as motion rather than an instant digit-swap. */
export function NumberTicker({
  value,
  format,
  className,
}: {
  value: number;
  format: (n: number) => string;
  className?: string;
}) {
  const spring = useSpring(value, { stiffness: 120, damping: 20, mass: 0.6 });
  const display = useTransform(spring, (v) => format(v));

  useEffect(() => {
    spring.set(value);
  }, [value, spring]);

  return (
    <motion.span className={className}>
      <motion.span>{display}</motion.span>
    </motion.span>
  );
}
