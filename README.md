# VoteSphere

VoteSphere is an educational election-management platform built with Django, PostgreSQL (or SQLite for local development), Django REST Framework, and optional Redis/Celery services. It is not a certified election system.

## Features

- Voter dashboard, searchable election directory, candidate profiles, notifications, and published results.
- Administrator and assigned-manager workflows in Django admin, with voter approval and audit history.
- Email verification, password reset, role/approval profiles, and sign-in throttling.
- Confirmation-based voting with atomic transactions and a database uniqueness constraint on voter participation.
- Anonymous ballots: the voter's election participation is stored separately from the candidate selection.
- Results are hidden until an authorized administrator or election manager publishes them.
- Versioned `/api/v1/` election, candidate, voting, results, dashboard, and admin analytics endpoints.
- Results caching, API throttling, and Celery email/notification tasks; Redis is optional for local development.

## Local setup

Use Python 3.11+ and install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set development configuration in the shell or a local, untracked `.env` file:

```text
DEBUG=True
SECRET_KEY=<generate-a-unique-secret>
```

Generate a key with:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`DATABASE_URL` is optional. When unset, the project uses SQLite. For PostgreSQL, configure `DATABASE_URL` with the connection string supplied by your database provider. Do not commit credentials.

Apply migrations and start Django:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Registration creates a pending voter profile. Email links are printed to the development console; verify the address, then approve the voter in Django admin. Existing users and votes are migrated forward: participation history is preserved, while the old voter-to-candidate association is removed. Back up the database before applying migrations to an existing deployment.

## Optional production services

Configure `REDIS_URL` to use Redis for shared caching. Set `CELERY_BROKER_URL` if the Celery broker uses a different URL, and run a worker:

```powershell
celery -A online_voting worker --loglevel=info
```

Configure `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` for outgoing mail. For deployment, set `DEBUG=False`, a persistent `SECRET_KEY`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS`, then run `python manage.py collectstatic` and serve the ASGI/WSGI app behind HTTPS.

## Deploying to Vercel

The included `vercel.json` routes requests to Django. Vercel's legacy `builds` configuration does not run Project Settings build commands, so WhiteNoise serves the checked-in files in `staticfiles/` using stable URLs. After changing CSS, images, or other static assets, run `python manage.py collectstatic --noinput` and include the updated `staticfiles/` files in your commit. In Vercel, use the repository folder containing `manage.py`, `requirements.txt`, and `vercel.json` as the project root. Add these environment variables before deploying:

- `SECRET_KEY`: generate a unique key and save it as a secret in Vercel; do not commit it.
- `DEBUG`: `False`.
- `DATABASE_URL`: a PostgreSQL connection URL from a persistent database provider. Vercel's local filesystem is ephemeral, so the project refuses to start on Vercel without this setting.
- `ALLOWED_HOSTS`: optional for the default `*.vercel.app` domain; set your custom domain(s), comma-separated, if you use one.
- `CSRF_TRUSTED_ORIGINS`: optional for `*.vercel.app`; add `https://your-domain.example` for each custom domain.
- SMTP settings listed above if registration verification, password resets, and voting emails should be delivered. Without a Redis broker, these tasks run synchronously in the web request; set `CELERY_TASK_ALWAYS_EAGER=False` only when a separate Celery worker is running.

Run `python manage.py migrate` once against the hosted PostgreSQL database before using the site, then create an administrator with `python manage.py createsuperuser`. Do not use the checked-in SQLite database for a Vercel deployment.

## API examples

- `GET /api/v1/elections/?status=active&search=annual`
- `GET /api/v1/elections/<id>/candidates/`
- `POST /api/v1/elections/<id>/vote/` with `{"candidate_id": 1}`
- `GET /api/v1/elections/<id>/results/`
- `GET /api/v1/dashboard/`
- `GET /api/v1/admin/analytics/`

Voting endpoints require an authenticated, email-verified, approved voter. Results remain private until publication.

## Validation

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test voting
```

The current implementation does not include WebSocket live updates, Docker/CI configuration, or cryptographic end-to-end ballot verification. Treat results and audit records as application-level controls; restrict database access and take verified backups for any deployment.
