"use client";

import { useEffect } from "react";
import { EmptyState } from "@/components/ui/empty-state";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="py-10">
      <EmptyState title="Something went wrong" hint={error.message} />
      <div className="mt-4 text-center">
        <button
          onClick={reset}
          className="min-h-[44px] rounded-lg bg-[var(--color-primary)] px-6 text-sm font-semibold text-white hover:bg-[var(--color-primary-strong)]"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
