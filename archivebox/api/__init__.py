__package__ = 'archivebox.api'

from rest_framework import routers
from .views import SnapshotViewset

router = routers.DefaultRouter()
router.register(r'snapshots', SnapshotViewset)
