"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bookmark } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";
import { JobCard, JobCardSkeleton, JobDetailSheet } from "@/components/jobs";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

export default function SavedPage() {
  const [open, setOpen] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["saved"], queryFn: () => api<Job[]>("/jobs/saved") });
  return (
    <div>
      <PageHeader title="Saved jobs" description="Jobs you bookmarked. Availability is re-checked on every RUN." />
      <div className="space-y-3">
        {q.isLoading ? (
          <JobCardSkeleton />
        ) : q.data?.length ? (
          q.data.map((j) => <JobCard key={j.id} job={j} onOpen={setOpen} />)
        ) : (
          <EmptyState icon={Bookmark} title="No saved jobs yet" description="Use the Save button on any job card to keep it here." />
        )}
      </div>
      <JobDetailSheet jobId={open} onClose={() => setOpen(null)} />
    </div>
  );
}
