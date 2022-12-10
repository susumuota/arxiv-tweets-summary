# arXiv Tweets Summary

Summarize top 20 most popular arXiv papers on Twitter in the last 7 days and post them to Slack / Twitter.

## Demo

- https://twitter.com/susumuota

## Google Cloud Run

This system is running on Google Cloud Run jobs.

- https://cloud.google.com/build/docs/build-push-docker-image
- https://cloud.google.com/run/docs/create-jobs#command-line
- https://cloud.google.com/scheduler/docs/creating#gcloud

## Create a project

- https://cloud.google.com/resource-manager/docs/creating-managing-projects#creating_a_project

```sh
export PROJECT_ID="arxiv-tweets-summary-2"
gcloud projects create $PROJECT_ID
gcloud projects list
# gcloud projects delete $PROJECT_ID
# unset PROJECT_ID
```

## Enable billing

Follow this instruction.

- https://cloud.google.com/billing/docs/how-to/modify-project#how-to-enable-billing
- https://console.cloud.google.com/billing/projects

Then confirm it.

```sh
gcloud beta billing projects describe $PROJECT_ID
```

It should show `billingEnabled: true`.

## Create a bucket

```sh
export GCS_BUCKET_NAME="tweets55"
export REGION="us-central1"
gcloud storage buckets create "gs://${GCS_BUCKET_NAME}" \
  --project=$PROJECT_ID \
  --location=$REGION \
  --public-access-prevention \
  --uniform-bucket-level-access
gcloud storage buckets list --project=$PROJECT_ID | grep name
# gcloud storage buckets delete "gs://${GCS_BUCKET_NAME}" --project=$PROJECT_ID
# unset GCS_BUCKET_NAME
```

## Build a Docker image on local machine and test it

- https://cloud.google.com/sdk/gcloud/reference/auth/application-default/login
- https://stackoverflow.com/a/50826145

Application settings.

```sh
export TWITTER_BEARER_TOKEN="secret info"
export TWITTER_API_KEY="secret info"
export TWITTER_API_KEY_SECRET="secret info"
export TWITTER_ACCESS_TOKEN="secret info"
export TWITTER_ACCESS_TOKEN_SECRET="secret info"
export DEEPL_AUTH_KEY="secret info"
export SLACK_BOT_TOKEN="secret info"
export SEARCH_PAGE_LIMIT="5"  # 200 on production env
export NOTIFY_TOP_N="5"       # 20 on production env
export SLACK_CHANNEL="#test"  # #anywhere on production env
```

Local test.

```sh
gcloud auth application-default login
cd docker
export IMAGE_NAME="arxiv-tweets-summary"
docker build -t $IMAGE_NAME .
docker run --rm \
  -e TWITTER_BEARER_TOKEN=$TWITTER_BEARER_TOKEN \
  -e TWITTER_API_KEY=$TWITTER_API_KEY \
  -e TWITTER_API_KEY_SECRET=$TWITTER_API_KEY_SECRET \
  -e TWITTER_ACCESS_TOKEN=$TWITTER_ACCESS_TOKEN \
  -e TWITTER_ACCESS_TOKEN_SECRET=$TWITTER_ACCESS_TOKEN_SECRET \
  -e DEEPL_AUTH_KEY=$DEEPL_AUTH_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  -e SEARCH_PAGE_LIMIT=$SEARCH_PAGE_LIMIT \
  -e NOTIFY_TOP_N=$NOTIFY_TOP_N \
  -e SLACK_CHANNEL=$SLACK_CHANNEL \
  -e GCS_BUCKET_NAME=$GCS_BUCKET_NAME \
  -e GCLOUD_PROJECT=$PROJECT_ID \
  -v $HOME/.config/gcloud:/root/.config/gcloud \
  $IMAGE_NAME
docker images
# docker rmi $IMAGE_NAME
# unset IMAGE_NAME
```

## Create a service account for Cloud Run

```sh
export RUN_SERVICE_ACCOUNT="run-sa"
gcloud iam service-accounts create $RUN_SERVICE_ACCOUNT --project=$PROJECT_ID
gcloud iam service-accounts list --project=$PROJECT_ID
# gcloud iam service-accounts delete $RUN_SERVICE_ACCOUNT --project=$PROJECT_ID
# unset RUN_SERVICE_ACCOUNT
```

## Add roles to service account to access GCS and to invoke Cloud Run

- https://cloud.google.com/storage/docs/access-control/iam-roles
- https://cloud.google.com/scheduler/docs/creating#gcloud
- https://cloud.google.com/iam/docs/creating-managing-service-accounts#creating
- https://codelabs.developers.google.com/cloud-run-jobs-and-cloud-scheduler#4

```sh
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
gcloud projects get-iam-policy $PROJECT_ID
# gcloud projects remove-iam-policy-binding $PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/storage.objectAdmin"
# gcloud projects remove-iam-policy-binding $PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/run.invoker"
```

## Create secret data

- https://cloud.google.com/secret-manager/docs/create-secret#secretmanager-quickstart-gcloud
- https://cloud.google.com/run/docs/configuring/secrets

```sh
gcloud services enable secretmanager.googleapis.com --project=$PROJECT_ID
echo -n $TWITTER_BEARER_TOKEN | gcloud secrets create "TWITTER_BEARER_TOKEN" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
echo -n $TWITTER_API_KEY | gcloud secrets create "TWITTER_API_KEY" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
echo -n $TWITTER_API_KEY_SECRET | gcloud secrets create "TWITTER_API_KEY_SECRET" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
echo -n $TWITTER_ACCESS_TOKEN | gcloud secrets create "TWITTER_ACCESS_TOKEN" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
echo -n $TWITTER_ACCESS_TOKEN_SECRET | gcloud secrets create "TWITTER_ACCESS_TOKEN_SECRET" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
echo -n $DEEPL_AUTH_KEY | gcloud secrets create "DEEPL_AUTH_KEY" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
echo -n $SLACK_BOT_TOKEN | gcloud secrets create "SLACK_BOT_TOKEN" \
  --project=$PROJECT_ID \
  --replication-policy="automatic" \
  --data-file=-
gcloud secrets list --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="TWITTER_BEARER_TOKEN" --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="TWITTER_API_KEY" --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="TWITTER_API_KEY_SECRET" --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="TWITTER_ACCESS_TOKEN" --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="TWITTER_ACCESS_TOKEN_SECRET" --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="DEEPL_AUTH_KEY" --project=$PROJECT_ID
gcloud secrets versions access 1 --secret="SLACK_BOT_TOKEN" --project=$PROJECT_ID
# gcloud secrets delete "TWITTER_BEARER_TOKEN" --project=$PROJECT_ID
# gcloud secrets delete "TWITTER_API_KEY" --project=$PROJECT_ID
# gcloud secrets delete "TWITTER_API_KEY_SECRET" --project=$PROJECT_ID
# gcloud secrets delete "TWITTER_ACCESS_TOKEN" --project=$PROJECT_ID
# gcloud secrets delete "TWITTER_ACCESS_TOKEN_SECRET" --project=$PROJECT_ID
# gcloud secrets delete "DEEPL_AUTH_KEY" --project=$PROJECT_ID
# gcloud secrets delete "SLACK_BOT_TOKEN" --project=$PROJECT_ID
# gcloud services disable secretmanager.googleapis.com --project=$PROJECT_ID
```

## Add roles to secrets to be accessed by service account

- https://cloud.google.com/secret-manager/docs/managing-secrets#secretmanager-create-secret-gcloud

```sh
gcloud secrets add-iam-policy-binding "TWITTER_BEARER_TOKEN" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "TWITTER_API_KEY" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "TWITTER_API_KEY_SECRET" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "TWITTER_ACCESS_TOKEN" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "TWITTER_ACCESS_TOKEN_SECRET" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "DEEPL_AUTH_KEY" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "SLACK_BOT_TOKEN" \
  --project=$PROJECT_ID \
  --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets get-iam-policy "TWITTER_BEARER_TOKEN" --project=$PROJECT_ID
gcloud secrets get-iam-policy "TWITTER_API_KEY" --project=$PROJECT_ID
gcloud secrets get-iam-policy "TWITTER_API_KEY_SECRET" --project=$PROJECT_ID
gcloud secrets get-iam-policy "TWITTER_ACCESS_TOKEN" --project=$PROJECT_ID
gcloud secrets get-iam-policy "TWITTER_ACCESS_TOKEN_SECRET" --project=$PROJECT_ID
gcloud secrets get-iam-policy "DEEPL_AUTH_KEY" --project=$PROJECT_ID
gcloud secrets get-iam-policy "SLACK_BOT_TOKEN" --project=$PROJECT_ID
# gcloud secrets remove-iam-policy-binding "TWITTER_BEARER_TOKEN" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
# gcloud secrets remove-iam-policy-binding "TWITTER_API_KEY" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
# gcloud secrets remove-iam-policy-binding "TWITTER_API_KEY_SECRET" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
# gcloud secrets remove-iam-policy-binding "TWITTER_ACCESS_TOKEN" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
# gcloud secrets remove-iam-policy-binding "TWITTER_ACCESS_TOKEN_SECRET" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
# gcloud secrets remove-iam-policy-binding "DEEPL_AUTH_KEY" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
# gcloud secrets remove-iam-policy-binding "SLACK_BOT_TOKEN" \
#   --project=$PROJECT_ID \
#   --member="serviceAccount:${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
#   --role="roles/secretmanager.secretAccessor"
```

## Create a Docker repository

- https://cloud.google.com/build/docs/build-push-docker-image
- https://codelabs.developers.google.com/cloud-run-jobs-and-cloud-scheduler#3

```sh
gcloud services enable artifactregistry.googleapis.com --project=$PROJECT_ID
export REPOSITORY="arxiv-tweets-summary"
gcloud artifacts repositories create $REPOSITORY \
  --project=$PROJECT_ID \
  --repository-format="docker" \
  --location=$REGION
gcloud artifacts repositories list --project=$PROJECT_ID
# gcloud artifacts repositories delete $REPOSITORY --project=$PROJECT_ID --location=$REGION
# gcloud services disable artifactregistry.googleapis.com --project=$PROJECT_ID
# unset REPOSITORY REGION
```

## Build a Docker image

- https://cloud.google.com/build/docs/build-push-docker-image
- https://cloud.google.com/build/docs/building/build-containers#use-dockerfile
- https://codelabs.developers.google.com/cloud-run-jobs-and-cloud-scheduler#3

```sh
gcloud services enable cloudbuild.googleapis.com --project=$PROJECT_ID
export TAG_NAME="latest"
gcloud builds submit \
  --project=$PROJECT_ID \
  --region=$REGION \
  --tag="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG_NAME}"
gcloud builds list --project=$PROJECT_ID --region=$REGION
gcloud artifacts repositories list --project=$PROJECT_ID
# gcloud services disable cloudbuild.googleapis.com --project=$PROJECT_ID
# unset TAG_NAME
```

## Test a Docker image on local machine

**This process may increase charge because of data transfer.**

- https://cloud.google.com/build/docs/building/build-containers#run_the_docker_image
- https://cloud.google.com/artifact-registry/pricing
- https://support.terra.bio/hc/en-us/articles/4408985788187-How-to-configure-GCR-Artifact-Registry-to-prevent-egress-charges

```sh
gcloud auth configure-docker ${REGION}-docker.pkg.dev
docker run --rm \
  -e TWITTER_BEARER_TOKEN=$TWITTER_BEARER_TOKEN \
  -e TWITTER_API_KEY=$TWITTER_API_KEY \
  -e TWITTER_API_KEY_SECRET=$TWITTER_API_KEY_SECRET \
  -e TWITTER_ACCESS_TOKEN=$TWITTER_ACCESS_TOKEN \
  -e TWITTER_ACCESS_TOKEN_SECRET=$TWITTER_ACCESS_TOKEN_SECRET \
  -e DEEPL_AUTH_KEY=$DEEPL_AUTH_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  -e SEARCH_PAGE_LIMIT=$SEARCH_PAGE_LIMIT \
  -e NOTIFY_TOP_N=$NOTIFY_TOP_N \
  -e SLACK_CHANNEL=$SLACK_CHANNEL \
  -e GCS_BUCKET_NAME=$GCS_BUCKET_NAME \
  -e GCLOUD_PROJECT=$PROJECT_ID \
  -v $HOME/.config/gcloud:/root/.config/gcloud \
  "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG_NAME}"
docker images
# docker rmi "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG_NAME}"
```

## Create a Cloud Run job

- https://cloud.google.com/run/docs/create-jobs#command-line

Change parameters for production env.

```sh
export SEARCH_PAGE_LIMIT="200"    # 5 on development env
export NOTIFY_TOP_N="20"          # 5 on development env
export SLACK_CHANNEL="#anywhere"  # #test on development env
```

```sh
gcloud services enable run.googleapis.com --project=$PROJECT_ID
export RUN_JOB_NAME="arxiv-tweets-summary-job-1"
gcloud beta run jobs create $RUN_JOB_NAME \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:${TAG_NAME}" \
  --project=$PROJECT_ID \
  --region=$REGION \
  --service-account="${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-secrets="TWITTER_BEARER_TOKEN=TWITTER_BEARER_TOKEN:1" \
  --set-secrets="TWITTER_API_KEY=TWITTER_API_KEY:1" \
  --set-secrets="TWITTER_API_KEY_SECRET=TWITTER_API_KEY_SECRET:1" \
  --set-secrets="TWITTER_ACCESS_TOKEN=TWITTER_ACCESS_TOKEN:1" \
  --set-secrets="TWITTER_ACCESS_TOKEN_SECRET=TWITTER_ACCESS_TOKEN_SECRET:1" \
  --set-secrets="DEEPL_AUTH_KEY=DEEPL_AUTH_KEY:1" \
  --set-secrets="SLACK_BOT_TOKEN=SLACK_BOT_TOKEN:1" \
  --set-env-vars="SEARCH_PAGE_LIMIT=${SEARCH_PAGE_LIMIT}" \
  --set-env-vars="NOTIFY_TOP_N=${NOTIFY_TOP_N}" \
  --set-env-vars="SLACK_CHANNEL=${SLACK_CHANNEL}" \
  --set-env-vars="GCS_BUCKET_NAME=${GCS_BUCKET_NAME}" \
  --max-retries=0 \
  --task-timeout="30m" \
  --memory="1024Mi"
gcloud beta run jobs list --project=$PROJECT_ID
gcloud beta run jobs describe $RUN_JOB_NAME --project=$PROJECT_ID --region=$REGION
# gcloud beta run jobs delete $RUN_JOB_NAME --project=$PROJECT_ID --region=$REGION
# gcloud services disable run.googleapis.com --project=$PROJECT_ID
# unset RUN_JOB_NAME
```

## Execute a job

- https://cloud.google.com/run/docs/execute/jobs

```sh
gcloud beta run jobs execute $RUN_JOB_NAME --project=$PROJECT_ID --region=$REGION
gcloud beta run jobs executions list --project=$PROJECT_ID --region=$REGION
```

```sh
gcloud logging read "resource.type=cloud_run_job" \
  --project=$PROJECT_ID \
  --limit 10 | egrep "textPayload|message"
```

## Create a Cloud Scheduler job

- https://cloud.google.com/run/docs/execute/jobs-on-schedule#command-line
- https://codelabs.developers.google.com/cloud-run-jobs-and-cloud-scheduler#4

```sh
export SCHEDULER_JOB_NAME="arxiv-tweets-summary-job-everyday-9am"
gcloud services enable cloudscheduler.googleapis.com --project=$PROJECT_ID
gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
  --project=$PROJECT_ID \
  --location=$REGION \
  --schedule="0 9 * * *" \
  --time-zone "Asia/Tokyo" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${RUN_JOB_NAME}:run" \
  --http-method="POST" \
  --oauth-service-account-email="${RUN_SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud scheduler jobs list --project=$PROJECT_ID --location=$REGION
gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --project=$PROJECT_ID --location=$REGION
# gcloud scheduler jobs delete $SCHEDULER_JOB_NAME --project=$PROJECT_ID --location=$REGION
# gcloud services disable cloudscheduler.googleapis.com --project=$PROJECT_ID
# unset SCHEDULER_JOB_NAME
```

```sh
gcloud logging read "resource.type=cloud_run_job OR resource.type=cloud_scheduler_job" \
  --project=$PROJECT_ID \
  --limit 10 | egrep "textPayload|message"
```

## License

MIT License, See LICENSE file.

## Author

Susumu OTA
