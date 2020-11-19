__package__ = 'archivebox.core'

import os
import sys

from pathlib import Path
from django.utils.crypto import get_random_string

from ..config import (                                                          # noqa: F401
    DEBUG,
    SECRET_KEY,
    ALLOWED_HOSTS,
    PACKAGE_DIR,
    ACTIVE_THEME,
    SQL_INDEX_FILENAME,
    OUTPUT_DIR,
)


IS_MIGRATING = 'makemigrations' in sys.argv[:3] or 'migrate' in sys.argv[:3]
IS_TESTING = 'test' in sys.argv[:3] or 'PYTEST_CURRENT_TEST' in os.environ
IS_SHELL = 'shell' in sys.argv[:3] or 'shell_plus' in sys.argv[:3]

################################################################################
### Django Core Settings
################################################################################

WSGI_APPLICATION = 'core.wsgi.application'
ROOT_URLCONF = 'core.urls'

LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = '/'
PASSWORD_RESET_URL = '/accounts/password_reset/'
APPEND_SLASH = True

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',

    'core',

    'django_extensions',
    'rest_framework',
]

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 100
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]


################################################################################
### Staticfile and Template Settings
################################################################################

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    str(Path(PACKAGE_DIR) / 'themes' / ACTIVE_THEME / 'static'),
    str(Path(PACKAGE_DIR) / 'themes' / 'default' / 'static'),
]

TEMPLATE_DIRS = [
    str(Path(PACKAGE_DIR) / 'themes' / ACTIVE_THEME),
    str(Path(PACKAGE_DIR) / 'themes' / 'default'),
    str(Path(PACKAGE_DIR) / 'themes'),
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': TEMPLATE_DIRS,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


################################################################################
### External Service Settings
################################################################################

DATABASE_FILE = Path(OUTPUT_DIR) / SQL_INDEX_FILENAME
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(DATABASE_FILE),
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


################################################################################
### Security Settings
################################################################################

SECRET_KEY = SECRET_KEY or get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789-_+!.')

ALLOWED_HOSTS = ALLOWED_HOSTS.split(',')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


################################################################################
### Shell Settings
################################################################################

SHELL_PLUS = 'ipython'
SHELL_PLUS_PRINT_SQL = False
IPYTHON_ARGUMENTS = ['--no-confirm-exit', '--no-banner']
IPYTHON_KERNEL_DISPLAY_NAME = 'ArchiveBox Django Shell'
if IS_SHELL:
    os.environ['PYTHONSTARTUP'] = str(Path(PACKAGE_DIR) / 'core' / 'welcome_message.py')


################################################################################
### Internationalization & Localization Settings
################################################################################

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_L10N = False
USE_TZ = False

DATETIME_FORMAT = 'Y-m-d g:iA'
SHORT_DATETIME_FORMAT = 'Y-m-d h:iA'
