__package__ = 'archivebox.core'

from io import StringIO
from contextlib import redirect_stdout

from django.contrib import admin
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django import forms

from ..util import htmldecode, urldecode, ansi_to_html

from core.models import Snapshot, Tag
from core.forms import AddLinkForm, TagField

from core.mixins import SearchResultsAdminMixin

from index.html import snapshot_icons
from logging_util import printable_filesize
from main import add, remove
from config import OUTPUT_DIR
from extractors import archive_snapshots

# Admin URLs
# /admin/
# /admin/login/
# /admin/core/
# /admin/core/snapshot/
# /admin/core/snapshot/:uuid/
# /admin/core/tag/
# /admin/core/tag/:uuid/


# TODO: https://stackoverflow.com/questions/40760880/add-custom-button-to-django-admin-panel

def update_snapshots(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], out_dir=OUTPUT_DIR)
update_snapshots.short_description = "Archive"

def update_titles(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], overwrite=True, methods=('title','favicon'), out_dir=OUTPUT_DIR)
update_titles.short_description = "Pull title"

def overwrite_snapshots(modeladmin, request, queryset):
    archive_links([
        snapshot.as_link()
        for snapshot in queryset
    ], overwrite=True, out_dir=OUTPUT_DIR)
overwrite_snapshots.short_description = "Re-archive (overwrite)"

def verify_snapshots(modeladmin, request, queryset):
    for snapshot in queryset:
        print(snapshot.timestamp, snapshot.url, snapshot.is_archived, snapshot.archive_size, len(snapshot.history))

verify_snapshots.short_description = "Check"

def delete_snapshots(modeladmin, request, queryset):
    remove(snapshots=queryset, yes=True, delete=True, out_dir=OUTPUT_DIR)

delete_snapshots.short_description = "Delete"


class SnapshotAdminForm(forms.ModelForm):
    tags = TagField(required=False)

    class Meta:
        model = Snapshot
        fields = "__all__"

    def save(self, commit=True):
        # Based on: https://stackoverflow.com/a/49933068/3509554

        # Get the unsave instance
        instance = forms.ModelForm.save(self, False)
        tags = self.cleaned_data.pop("tags")

        #update save_m2m
        def new_save_m2m():
            instance.save_tags(tags)

        # Do we need to save all changes now?
        self.save_m2m = new_save_m2m
        if commit:
            instance.save()

        return instance


class SnapshotAdmin(SearchResultsAdminMixin, admin.ModelAdmin):
    list_display = ('added', 'title_str', 'url_str', 'files', 'size')
    sort_fields = ('title_str', 'url_str', 'added')
    readonly_fields = ('id', 'url', 'timestamp', 'num_outputs', 'is_archived', 'url_hash', 'added', 'updated')
    search_fields = ['url__icontains', 'timestamp', 'title', 'tags__name']
    fields = (*readonly_fields, 'title', 'tags')
    list_filter = ('added', 'updated', 'tags')
    ordering = ['-added']
    actions = [delete_snapshots, overwrite_snapshots, update_snapshots, update_titles, verify_snapshots]
    actions_template = 'admin/actions_as_select.html'
    form = SnapshotAdminForm
    list_per_page = 40

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('grid/', self.admin_site.admin_view(self.grid_view),name='grid')
        ]
        return custom_urls + urls

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('tags')

    def tag_list(self, obj):
        return ', '.join(obj.tags.values_list('name', flat=True))

    def id_str(self, obj):
        return format_html(
            '<code style="font-size: 10px">{}</code>',
            obj.url_hash[:8],
        )

    def title_str(self, obj):
        canon = obj.as_link().canonical_outputs()
        tags = ''.join(
            format_html('<a href="/admin/core/snapshot/?tags__id__exact={}"><span class="tag">{}</span></a> ', tag.id, tag)
            for tag in obj.tags.all()
            if str(tag).strip()
        )
        return format_html(
            '<a href="/{}">'
                '<img src="/{}/{}" class="favicon" onerror="this.remove()">'
            '</a>'
            '<a href="/{}/index.html">'
                '<b class="status-{}">{}</b>'
            '</a>',
            obj.archive_path,
            obj.archive_path, canon['favicon_path'],
            obj.archive_path,
            'fetched' if obj.latest_title or obj.title else 'pending',
            urldecode(htmldecode(obj.latest_title or obj.title or ''))[:128] or 'Pending...'
        ) + mark_safe(f' <span class="tags">{tags}</span>')

    def files(self, obj):
        return snapshot_icons(obj)

    def size(self, obj):
        archive_size = obj.archive_size
        if archive_size:
            size_txt = printable_filesize(archive_size)
            if archive_size > 52428800:
                size_txt = mark_safe(f'<b>{size_txt}</b>')
        else:
            size_txt = mark_safe('<span style="opacity: 0.3">...</span>')
        return format_html(
            '<a href="/{}" title="View all files">{}</a>',
            obj.archive_path,
            size_txt,
        )

    def url_str(self, obj):
        return format_html(
            '<a href="{}"><code>{}</code></a>',
            obj.url,
            obj.url.split('://www.', 1)[-1].split('://', 1)[-1][:64],
        )

    def grid_view(self, request):

        # cl = self.get_changelist_instance(request)

        # Save before monkey patching to restore for changelist list view
        saved_change_list_template = self.change_list_template
        saved_list_per_page = self.list_per_page
        saved_list_max_show_all = self.list_max_show_all

        # Monkey patch here plus core_tags.py
        self.change_list_template = 'private_index_grid.html'
        self.list_per_page = 20
        self.list_max_show_all = self.list_per_page

        # Call monkey patched view
        rendered_response = self.changelist_view(request)

        # Restore values
        self.change_list_template =  saved_change_list_template
        self.list_per_page = saved_list_per_page
        self.list_max_show_all = saved_list_max_show_all

        return rendered_response
        

    id_str.short_description = 'ID'
    title_str.short_description = 'Title'
    url_str.short_description = 'Original URL'

    id_str.admin_order_field = 'id'
    title_str.admin_order_field = 'title'
    url_str.admin_order_field = 'url'

class TagAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'id')
    sort_fields = ('id', 'name', 'slug')
    readonly_fields = ('id',)
    search_fields = ('id', 'name', 'slug')
    fields = (*readonly_fields, 'name', 'slug')


class ArchiveBoxAdmin(admin.AdminSite):
    site_header = 'ArchiveBox'
    index_title = 'Links'
    site_title = 'Index'

    def get_urls(self):
        return [
            path('core/snapshot/add/', self.add_view, name='Add'),
        ] + super().get_urls()

    def add_view(self, request):
        if not request.user.is_authenticated:
            return redirect(f'/admin/login/?next={request.path}')

        request.current_app = self.name
        context = {
            **self.each_context(request),
            'title': 'Add URLs',
        }

        if request.method == 'GET':
            context['form'] = AddLinkForm()

        elif request.method == 'POST':
            form = AddLinkForm(request.POST)
            if form.is_valid():
                url = form.cleaned_data["url"]
                print(f'[+] Adding URL: {url}')
                depth = 0 if form.cleaned_data["depth"] == "0" else 1
                input_kwargs = {
                    "urls": url,
                    "depth": depth,
                    "update_all": False,
                    "out_dir": OUTPUT_DIR,
                }
                add_stdout = StringIO()
                with redirect_stdout(add_stdout):
                   add(**input_kwargs)
                print(add_stdout.getvalue())

                context.update({
                    "stdout": ansi_to_html(add_stdout.getvalue().strip()),
                    "form": AddLinkForm()
                })
            else:
                context["form"] = form

        return render(template_name='add.html', request=request, context=context)

admin.site = ArchiveBoxAdmin()
admin.site.register(get_user_model())
admin.site.register(Snapshot, SnapshotAdmin)
admin.site.register(Tag, TagAdmin)
admin.site.disable_action('delete_selected')
