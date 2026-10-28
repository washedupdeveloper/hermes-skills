# Spec Delta

## ADDED Requirements

### Requirement: A run's cost is a number, not an inference

A workflow run SHALL publish how long each of its jobs took, in the run itself, without requiring
anyone to read two timestamps from an API response.

#### Scenario: A job is slow or vanishes

- **WHEN** a job runs long, or is cancelled without executing a step
- **THEN** the run's summary states that job's elapsed time and its conclusion

#### Scenario: A job is still running

- **WHEN** the cost is rendered while a job has not finished
- **THEN** that job shows no duration rather than zero, because zero is a claim about the work

#### Scenario: The number is read as a total

- **WHEN** the table is published
- **THEN** the run's span is distinguished from the sum of the jobs, because jobs overlap
