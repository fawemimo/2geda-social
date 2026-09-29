from django.contrib.postgres.indexes import GinIndex
from django.db.models import Index


class TrigramGinIndex(GinIndex):
  

    def create_sql(self, model, schema_editor, using="", **kwargs):
        if schema_editor.connection.vendor == "postgresql" or not self.expressions:
            # Also covers a GinIndex built from `fields=`, which already
            # degrades to a plain index on non-PostgreSQL backends.
            return super().create_sql(model, schema_editor, using=using, **kwargs)

        columns = [
            expression.get_source_expressions()[0] for expression in self.expressions
        ]
        return Index(*columns, name=self.name).create_sql(
            model, schema_editor, using="", **kwargs
        )
