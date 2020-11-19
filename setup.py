import json
import setuptools

from pathlib import Path


PKG_NAME = "archivebox"
DESCRIPTION = "The self-hosted internet archive."
LICENSE = "MIT"
AUTHOR = "Nick Sweeting"
AUTHOR_EMAIL="git@nicksweeting.com"
REPO_URL = "https://github.com/pirate/ArchiveBox"
PROJECT_URLS = {
    "Source":           f"{REPO_URL}",
    "Documentation":    f"{REPO_URL}/wiki",
    "Bug Tracker":      f"{REPO_URL}/issues",
    "Changelog":        f"{REPO_URL}/wiki/Changelog",
    "Roadmap":          f"{REPO_URL}/wiki/Roadmap",
    "Community":        f"{REPO_URL}/wiki/Web-Archiving-Community",
    "Donate":           f"{REPO_URL}/wiki/Donations",
}

ROOT_DIR = Path(__file__).parent.resolve()
PACKAGE_DIR = ROOT_DIR / PKG_NAME

README = (PACKAGE_DIR / "README.md").read_text()
VERSION = json.loads((PACKAGE_DIR / "package.json").read_text().strip())['version']

# To see when setup.py gets called (uncomment for debugging):
# import sys
# print(PACKAGE_DIR, f"     (v{VERSION})")
# print('>', sys.executable, *sys.argv)


setuptools.setup(
    name=PKG_NAME,
    version=VERSION,
    license=LICENSE,
    author=AUTHOR,
    author_email=AUTHOR_EMAIL,
    description=DESCRIPTION,
    long_description=README,
    long_description_content_type="text/markdown",
    url=REPO_URL,
    project_urls=PROJECT_URLS,
    python_requires=">=3.7",
    setup_requires=[
        "wheel",
    ],
    install_requires=[
        "requests==2.24.0",
        "atomicwrites==1.4.0",
        "mypy-extensions==0.4.3",
        "base32-crockford==0.3.0",
        "django==3.0.8",
        "django-extensions==3.0.3",
        "djangorestframework==3.12.2",

        "dateparser",
        "ipython",
        "youtube-dl",
        "python-crontab==2.5.1",
        "croniter==0.3.34",
        "w3lib==1.22.0",
        # Some/all of these will likely be added in the future:
        # wpull
        # pywb
        # pyppeteer
        # archivenow
    ],
    extras_require={
        'dev': [
            "setuptools",
            "twine",
            "flake8",
            "ipdb",
            "mypy",
            "django-stubs",
            "sphinx",
            "sphinx-rtd-theme",
            "recommonmark",
            "pytest",
            "bottle",
        ],
        # 'redis': ['redis', 'django-redis'],
        # 'pywb': ['pywb', 'redis'],
    },
    packages=[PKG_NAME],
    include_package_data=True,   # see MANIFEST.in
    entry_points={
        "console_scripts": [
            f"{PKG_NAME} = {PKG_NAME}.cli:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",

        "Topic :: Utilities",
        "Topic :: System :: Archiving",
        "Topic :: System :: Archiving :: Backup",
        "Topic :: System :: Recovery Tools",
        "Topic :: Sociology :: History",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Topic :: Software Development :: Libraries :: Python Modules",

        "Intended Audience :: Developers",
        "Intended Audience :: Education",
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Information Technology",
        "Intended Audience :: Legal Industry",
        "Intended Audience :: System Administrators",
        
        "Environment :: Console",
        "Environment :: Web Environment",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Framework :: Django",
        "Typing :: Typed",
    ],
)
