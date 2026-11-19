import { Skeleton } from "@/components/ui/skeleton";

export default function CustomerLoading() {
  return <div className="space-y-4" aria-busy="true">
    <Skeleton className="h-11 w-40" />
    <Skeleton className="h-32 w-full" />
    <div className="grid gap-3 sm:grid-cols-2">
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  </div>;
}
