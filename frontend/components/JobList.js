import Link from "next/link";
import { badge, formatSize } from "@/lib/status";

// The "past uploads" table. Each row links to the job page.
export default function JobList({ jobs }) {
  if (jobs.length === 0) {
    return <p className="muted">Nothing uploaded yet. Your uploads will be listed here.</p>;
  }
  return (
    <ul className="jobs">
      {jobs.map((job) => {
        const { label, tone } = badge(job);
        return (
          <li key={job.id}>
            <Link href={`/jobs/${job.id}`} className="job-row">
              <span className="job-name">{job.filename}</span>
              <span className="muted">
                {formatSize(job.size_bytes)} · {new Date(job.created_at).toLocaleString()}
              </span>
              <span className={`badge ${tone}`}>{label}</span>
              <span className="open">Open →</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
