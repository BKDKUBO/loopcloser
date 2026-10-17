# Firestore backup and recovery

Not set up yet. These steps run at deploy time (week 2), after the team approves the costs.

1. **Point-in-time recovery (PITR).** `deploy/deploy.sh` creates the `(default)` database in the LoopCloser project with
   `--enable-pitr`. That keeps 7 days of versions, so a bad write can be read back from any minute in that window.
2. **Scheduled backups.** Daily backup, kept 14 days:
   ```
   gcloud firestore backups schedules create --database="(default)" --recurrence=daily --retention=14d
   ```
3. **Restore drill** (do it once before the demo):
   ```
   gcloud firestore backups list --location=asia-southeast1
   gcloud firestore databases restore --source-backup=<backup-name> --destination-database=loopcloser-restore-test
   ```
   Then point a local API at `FIRESTORE_DATABASE=loopcloser-restore-test` and call
   `POST /api/admin/cases/{id}/verify-projection` on a few cases.
4. **Projections are rebuildable.** Case documents are a cache of the event log, so a damaged projection
   is rebuilt from `cases/{id}/events`. Lost events are what the backups protect.
5. **Synthetic data only.** No real patient data is stored, so there is no PHI in any backup.

Check current Firestore backup and PITR pricing before enabling. We have not estimated it yet.
