from django.db import models
from django.conf import settings

from widgy.models import Content
from widgy.models.mixins import StrictDefaultChildrenMixin, InvisibleMixin
from widgy.db.fields import WidgyField
from widgy.contrib.page_builder.db.fields import MarkdownField
from widgy import registry


class PageBuilderContent(Content):
    """
    Base class for all page builder content models.
    """
    class Meta:
        abstract = True


class Layout(StrictDefaultChildrenMixin, PageBuilderContent):
    """
    Base class for all layouts.
    """
    class Meta:
        abstract = True

    draggable = False
    deletable = False

    @classmethod
    def valid_child_of(cls, content, obj=None):
        return False


class Bucket(PageBuilderContent):
    draggable = False
    deletable = False
    accepting_children = True

    class Meta:
        abstract = True


class MainContent(Bucket):
    def valid_parent_of(self, cls, obj=None):
        return not issubclass(cls, (MainContent, Sidebar))

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return isinstance(parent, Layout)

registry.register(MainContent)


class Sidebar(Bucket):
    pop_out = 1

    def to_json(self, site):
        from datetime import datetime
        json = super(Sidebar, self).to_json(site)
        json['content'] = str(datetime.now())
        return json

    def valid_parent_of(self, cls, obj=None):
        return not issubclass(cls, (MainContent, Sidebar))

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return isinstance(parent, Layout)

registry.register(Sidebar)


class DefaultLayout(Layout):
    """
    On creation, creates a left and right bucket.
    """
    class Meta:
        verbose_name = 'Default layout'

    default_children = [
        (MainContent, (), {}),
        (Sidebar, (), {}),
    ]

registry.register(DefaultLayout)


class Markdown(Content):
    content = MarkdownField(blank=True)
    rendered = models.TextField(editable=False)

    editable = True
    component_name = 'markdown'

registry.register(Markdown)


class CalloutBucket(Bucket):
    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return False

    def valid_parent_of(self, cls, obj=None):
        return issubclass(cls, (Markdown,))

registry.register(CalloutBucket)


class Callout(models.Model):
    name = models.CharField(max_length=255)
    root_node = WidgyField(
        site=settings.WIDGY_MEZZANINE_SITE,
        verbose_name='Widgy Content',
        root_choices=(
            'CalloutBucket',
        ))

    def __unicode__(self):
        return self.name


class CalloutWidget(Content):
    callout = models.ForeignKey(Callout, null=True, blank=True)

    editable = True

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return isinstance(parent, Sidebar)

registry.register(CalloutWidget)


class Accordion(Bucket):
    draggable = True
    deletable = True

    def valid_parent_of(self, cls, obj=None):
        return issubclass(cls, Section)

registry.register(Accordion)


class Section(Content):
    title = models.CharField(max_length=1023)

    editable = True
    accepting_children = True

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return isinstance(parent, Accordion)

registry.register(Section)


class TableElement(Content):
    class Meta:
        abstract = True

    @property
    def table(self):
        for i in reversed(self.get_ancestors()):
            if isinstance(i, Table):
                return i
        assert False, "This TableElement isn't in a table?!?"

    def get_siblings(self):
        return list(self.get_parent().get_children())

    @property
    def sibling_index(self):
        return self.get_siblings().index(self)


class TableRow(TableElement):
    tag_name = 'tr'

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return isinstance(parent, TableBody)

    def valid_parent_of(self, cls, obj=None):
        return issubclass(cls, TableData)

    def post_create(self, site):
        for column in self.table.header.children:
            self.add_child(site, TableData)


class TableHeaderData(TableElement):
    tag_name = 'th'

    accepting_children = True
    draggable = True
    deletable = True

    class Meta:
        verbose_name = 'column'

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        if obj and obj.get_parent():
            # we can't be moved to another table
            return obj in parent.children
        else:
            return isinstance(parent, TableHeader)

    def post_create(self, site):
        right = self.get_next_sibling()
        if right:
            for d in self.table.cells_at_index(right.sibling_index - 1):
                d.add_sibling(site, TableData)
        else:
            for row in self.table.body.children:
                row.add_child(site, TableData)

    def pre_delete(self):
        for i in self.table.cells_at_index(self.sibling_index):
            i.node.delete()

    def reposition(self, site, right=None, parent=None):
        # we must always stay in the same table
        assert not parent or self.get_parent() == parent

        prev_index = self.sibling_index
        right_index = right and right.sibling_index

        super(TableHeaderData, self).reposition(site, right, parent)

        if right:
            new_rights = self.table.cells_at_index(right_index)
        else:
            new_rights = [None] * len(self.get_siblings())

        for (i, new_right) in zip(self.table.cells_at_index(prev_index), new_rights):
            i.reposition(site, new_right, i.get_parent())


class TableData(TableElement):
    tag_name = 'td'

    accepting_children = True
    draggable = False
    deletable = False

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        # this is kind of a hack -- we are valid children of TableRow, but we
        # can't be added from the shelf
        if obj:
            return isinstance(parent, TableRow)
        else:
            return False


class TableHeader(TableElement):
    draggable = False
    deletable = False
    component_name = 'tableheader'

    class Meta:
        verbose_name = 'columns'

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        if obj in parent.children:
            return True
        return (isinstance(parent, Table) and
                len([i for i in parent.children if isinstance(i, cls)]) < 1)

    def valid_parent_of(self, cls, obj=None):
        return issubclass(cls, TableHeaderData)


class TableBody(InvisibleMixin, TableElement):
    tag_name = 'tbody'

    draggable = False
    deletable = False

    @classmethod
    def valid_child_of(cls, parent, obj=None):
        return isinstance(parent, Table)

    def valid_parent_of(self, cls, obj=None):
        if obj:
            if obj in self.children:
                return True
            if isinstance(obj, TableRow) and len(obj.children) == len(self.table.header.children):
                return True
        else:
            return issubclass(cls, TableRow)


class Table(StrictDefaultChildrenMixin, TableElement):
    tag_name = 'table'
    component_name = 'table'

    shelf = True

    default_children = [
        (TableHeader, (), {}),
        (TableBody, (), {}),
    ]

    @property
    def pop_out(self):
        for i in self.get_ancestors():
            if isinstance(i, Table):
                return 2
        return 0

    @property
    def header(self):
        return self.children[0]

    @property
    def body(self):
        return self.children[1]

    def cells_at_index(self, index):
        return [list(i.get_children())[index] for i in self.body.children]

registry.register(Table)
registry.register(TableRow)
registry.register(TableData)
registry.register(TableHeaderData)
registry.register(TableHeader)
