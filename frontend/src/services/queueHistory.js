export function canDeleteJob(job) {
  return ['succeeded', 'failed', 'interrupted', 'cancelled'].includes(job?.status)
}

export function canCancelJob(job) {
  return ['queued', 'running'].includes(job?.status)
}

export function canRetryJob(job, jobs) {
  return ['failed', 'interrupted'].includes(job?.status)
    && !jobs.some(candidate => candidate.retry_of === job.job_id
      && ['queued', 'running', 'cancelling'].includes(candidate.status))
}
