import traceback
import copy

from django.db import models as dja_fields
from djongo.models import fields as djm_fields
from rest_framework import fields as drf_fields
from rest_framework import serializers
from rest_framework.settings import api_settings
from rest_framework.utils.field_mapping import get_nested_relation_kwargs

from .fields import EmbeddedModelField, ArrayModelField, ObjectIdField
from rest_meets_djongo import meta_manager


def raise_errors_on_nested_writes(method_name, serializer, validated_data):
    """
    Replacement for DRF, allows for EmbeddedModelFields to not cause an error
    """
    # Make sure the field is a format which can be managed by the method
    assert not any(
        isinstance(field, serializers.BaseSerializer) and
        (field.source in validated_data) and
        isinstance(validated_data[field.source], (list, dict)) and
        not isinstance(field, EmbeddedModelSerializer)
        for field in serializer._writable_fields), (
        'The method `{method_name}` does not support this form of '
        'writable nested field by default.\nWrite a custom version of '
        'the method for `{module}.{class_name}` or set the field to '
        '`read_only=True`'.format(
            method_name=method_name,
            module=serializer.__class__.__module__,
            class_name=serializer.__class__.__name__
        )
    )

    # Make sure dotted-source fields weren't passed
    assert not any(
        '.' in field.source and
        (key in validated_data) and
        isinstance(validated_data[key], (list, dict))
        for key, field in serializer.fields.items()
    ), (
        'The `.{method_name}()` method does not support writable dotted-source '
        'fields by default.\nWrite an explicit `.{method_name}()` method for '
        'serializer `{module}.{class_name}`, or set `read_only=True` on '
        'dotted-source serializer fields.'.format(
            method_name=method_name,
            module=serializer.__class__.__module__,
            class_name=serializer.__class__.__name__
        )
    )


class DjongoModelSerializer(serializers.ModelSerializer):
    """
    A modification of DRF's ModelSerializer to allow for EmbeddedModelFields
    to be easily handled.

    Automatically generates fields for the model, accounting for embedded
    model fields in the process
    """

    serializer_field_mapping = {
        # Original DRF field mappings (Django Derived)
        dja_fields.AutoField: drf_fields.IntegerField,
        dja_fields.BigIntegerField: drf_fields.IntegerField,
        dja_fields.BooleanField: drf_fields.BooleanField,
        dja_fields.CharField: drf_fields.CharField,
        dja_fields.CommaSeparatedIntegerField: drf_fields.CharField,
        dja_fields.DateField: drf_fields.DateField,
        dja_fields.DateTimeField: drf_fields.DateTimeField,
        dja_fields.DecimalField: drf_fields.DecimalField,
        dja_fields.EmailField: drf_fields.EmailField,
        dja_fields.Field: drf_fields.ModelField,
        dja_fields.FileField: drf_fields.FileField,
        dja_fields.FloatField: drf_fields.FloatField,
        dja_fields.ImageField: drf_fields.ImageField,
        dja_fields.IntegerField: drf_fields.IntegerField,
        dja_fields.NullBooleanField: drf_fields.NullBooleanField,
        dja_fields.PositiveIntegerField: drf_fields.IntegerField,
        dja_fields.PositiveSmallIntegerField: drf_fields.IntegerField,
        dja_fields.SlugField: drf_fields.SlugField,
        dja_fields.SmallIntegerField: drf_fields.IntegerField,
        dja_fields.TextField: drf_fields.CharField,
        dja_fields.TimeField: drf_fields.TimeField,
        dja_fields.URLField: drf_fields.URLField,
        dja_fields.GenericIPAddressField: drf_fields.IPAddressField,
        dja_fields.FilePathField: drf_fields.FilePathField,
        # REST-meets-Djongo field mappings (Djongo Derived)
        djm_fields.ObjectIdField: ObjectIdField,
        djm_fields.EmbeddedModelField: EmbeddedModelField,
        djm_fields.ArrayModelField: ArrayModelField,
    }

    # Easy trigger variable for use in inherited classes (IE EmbeddedModels)
    _saving_instances = True

    def recursive_save(self, validated_data, instance=None):
        """
        Recursively traverses provided validated data, creating
        EmbeddedModels w/ the correct class as it does so

        Returns a Model instance of the model designated by the user
        """
        obj_data = {}

        for key, val in validated_data.items():
            try:
                field = self.fields[key]

                # For other embedded models, recursively build their fields too
                if isinstance(field, EmbeddedModelSerializer):
                    obj_data[key] = field.recursive_save(val)

                # For embedded models not provided and explicit serializer,
                #   build the default
                elif isinstance(field, EmbeddedModelField):
                    obj_data[key] = field.model_field(**val)

                # For lists of embedded models, build each object as above
                elif ((isinstance(field, serializers.ListSerializer) or
                        isinstance(field, serializers.ListField)) and
                       isinstance(field.child, EmbeddedModelSerializer)):
                    obj_data[key] = []
                    for datum in val:
                        obj_data[key].append(field.child.recursive_save(datum))

                # For ArrayModelFields, do above (with a different reference)
                # WIP
                elif isinstance(field, djm_fields.ArrayModelField):
                    obj_data[key] = field.value_from_object(val)

                else:
                    obj_data[key] = val

            # Dynamic data (Shouldn't exist with current Djongo, but may
            # appear in future)
            except KeyError:
                obj_data = val

        # Update the provided instance, or create a new one
        if instance is None:
            instance = self.Meta.model(**obj_data)
        else:
            for key, val in obj_data.items():
                setattr(instance, key, val)

        # Save the instance (overridden for EmbeddedModels, below)
        if self._saving_instances:
            instance.save()

        return instance

    def create(self, validated_data):
        raise_errors_on_nested_writes('create', self, validated_data)

        model_class = self.Meta.model

        try:
            return self.recursive_save(validated_data)
        except TypeError:
            tb = traceback.format_exc()
            msg = (
                    'Got a `TypeError` when calling `%s.%s.create()`. '
                    'This may be because you have a writable field on the '
                    'serializer class that is not a valid argument to '
                    '`%s.%s.create()`. You may need to make the field '
                    'read-only, or override the %s.create() method to handle '
                    'this correctly.\nOriginal exception was:\n %s' %
                    (
                        model_class.__name__,
                        model_class._default_manager.name,
                        model_class.__name__,
                        model_class._default_manager.name,
                        self.__class__.__name__,
                        tb
                    )
            )
            raise TypeError(msg)

    def update(self, instance, validated_data):
        raise_errors_on_nested_writes('update', self, validated_data)

        return self.recursive_save(validated_data, instance)

    def to_internal_value(self, data):
        """
        Borrows DRF's implimentation, but creates initial and validated
        data for EmbeddedModels so recursive save can correctly use them

        Arbitrary data is silently dropped from validated data, as to avoid
        issues down the line (assignment to an attribute which doesn't exist)
        """

        for field in self._writable_fields:
            if (isinstance(field, EmbeddedModelSerializer) and
                    field.field_name in data):
                field.initial_data = data[field.field_name]

        ret = super(DjongoModelSerializer, self).to_internal_value(data)

        for field in self._writable_fields:
            if (isinstance(field, EmbeddedModelSerializer) and
                    field.field_name in ret):
                field._validated_data = ret[field.field_name]

        return ret

    def get_fields(self):
        """
        An override of DRF to enable EmbeddedModelFields to be correctly
        caught and built
        """
        if self.url_field_name is None:
            self.url_field_name = api_settings.URL_FIELD_NAME

        assert hasattr(self, 'Meta'), (
            'Class {serializer_class} missing "Meta" attribute'.format(
                serializer_class=self.__class__.__name__
            )
        )

        assert hasattr(self.Meta, 'model'), (
            "Class {serializer_name} missing `Meta.model` attribute".format(
                serializer_name=self.__class__.__name__
            )
        )

        if meta_manager.is_model_abstract(self.Meta.model):
            raise ValueError(
                "Cannot use DjongoModelSerializer w/ Abstract Models.\n"
                "Consider using EmbeddedModelSerializer instead."
            )

        # Fetch and check useful metadata parameters
        declared_fields = copy.deepcopy(self._declared_fields)
        model = getattr(self.Meta, 'model')
        rel_depth = getattr(self.Meta, 'depth', 0)
        emb_depth = getattr(self.Meta, 'embed_depth', 5)

        assert rel_depth >= 0, "'depth' may not be negative"
        assert rel_depth <= 10, "'depth' may not be greater than 10"

        assert emb_depth >= 0, "'embed_depth' may not be negative"

        # Fetch information about the fields for our model class
        info = meta_manager.get_field_info(model)
        field_names = self.get_field_names(declared_fields, info)

        # Determine extra field arguments + hidden fields that need to
        # be included
        extra_kwargs = self.get_extra_kwargs()
        extra_kwargs, hidden_fields = self.get_uniqueness_extra_kwargs(
            field_names, declared_fields, extra_kwargs
        )

        # Find fields which are required for the serializer
        fields = {}

        for field_name in field_names:
            # Fields explicitly declared should always be used
            if field_name in declared_fields:
                fields[field_name] = declared_fields[field_name]
                continue

            extra_field_kwargs = extra_kwargs.get(field_name, {})
            source = extra_field_kwargs.get('source', field_name)
            if source == '*':
                source = field_name

            # Determine field class and keyword arguments
            field_class, field_kwargs = self.build_field(
                source, info, model, rel_depth, emb_depth
            )

            # Fetch any extra_kwargs specified by the meta
            field_kwargs = self.include_extra_kwargs(
                field_kwargs, extra_field_kwargs
            )

            # Create the serializer field
            fields[field_name] = field_class(**field_kwargs)

        # Update with any hidden fields
        fields.update(hidden_fields)

        return fields

    def get_field_names(self, declared_fields, info):
        """
        Override of DRF's function, enabling EmbeddedModelFields to be
        caught and handled. Some slight optimization is also provided.
        (Useful given how many nested models may need to be iterated over)

        Will include only direct children of the serializer; no
        grandchildren are included by default
        """
        fields = getattr(self.Meta, 'fields', None)
        exclude = getattr(self.Meta, 'exclude', None)

        # Confirm that both were not provided, which is invalid
        assert not (fields and exclude), (
            "Cannot set both 'fields' and 'exclude' options on "
            "serializer {serializer_class}.".format(
                serializer_class=self.__class__.__name__
            )
        )

        # If the user specified a `fields` attribute in Meta
        if fields is not None:
            # If the user just wants all fields...
            if fields == serializers.ALL_FIELDS:
                return self.get_default_field_names(declared_fields, info)
            # If the user specified fields explicitly...
            elif isinstance(fields, (list, tuple)):
                # Check to make sure all declared fields (required for creation)
                # were specified by the user
                required_field_names = set(declared_fields)
                for cls in self.__class__.__bases__:
                    required_field_names -= set(getattr(cls, '_declared_fields', []))

                for field_name in required_field_names:
                    assert field_name in fields, (
                        "The field '{field_name}' was declared on serializer "
                        "{serializer_class}, but has not been included in the "
                        "'fields' option.".format(
                            field_name=field_name,
                            serializer_class=self.__class__.__name__
                        )
                    )
            # If the user didn't provide a field set in the proper format...
            else:
                raise TypeError(
                    'The `fields` option must be a list or tuple or "__all__". '
                    'Got {cls_name}.'.format(cls_name=type(fields).__name__)
                )
        # If the user specified an `exclude` attribute in Meta
        elif exclude is not None:
            fields = self.get_default_field_names(declared_fields, info)

            # Ignore nested field customization; they're handled later
            for field_name in [name for name in exclude if '.' not in name]:
                assert field_name not in self._declared_fields, (
                    "Cannot both declare the field '{field_name}' and include "
                    "it in the {serializer_class} 'exclude' option. Remove the "
                    "field or, if inherited from a parent serializer, disable "
                    "with `{field_name} = None`.".format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )

                assert field_name in fields, (
                    "The field '{field_name}' was included on serializer "
                    "{serializer_class} in the 'exclude' option, but does "
                    "not match any model field.".format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )

                fields.remove(field_name)
        # If the user failed to provide either...
        else:
            raise AssertionError(
                "Creating a ModelSerializer without either the 'fields' attribute "
                "or the 'exclude' attribute has been deprecated and is now " 
                "disallowed. Add an explicit fields = '__all__' to the "
                "{serializer_class} serializer.".format(
                    serializer_class=self.__class__.__name__
                )
            )

        # Filter out child fields, which are automatically contained in a child
        # instance anyways
        return [name for name in fields if '.' not in name]

    def get_default_field_names(self, declared_fields, model_info):
        return (
            [model_info.pk.name] +
            list(declared_fields.keys()) +
            list(model_info.fields.keys()) +
            list(model_info.forward_relations.keys()) +
            list(model_info.embedded_fields.keys())
        )

    def build_field(self, field_name, info, model_class, nested_depth, embed_depth):
        # Temporary cast to allow code to function
        # TODO: Build this function fully
        return super().build_field(field_name, info, model_class, nested_depth)

    # TODO: Distinguish between this and the soon-to-be-added build_embed_field
    def build_nested_field(self, field_name, relation_info, nested_depth):
        """
        Create nested fields for forward/reverse relations

        Slight tweak of DRF's variant, as to allow the nested serializer
        to use our specified field mappings
        """
        class NestedRelationSerializer(DjongoModelSerializer):
            class Meta:
                model = relation_info.related_model
                depth = nested_depth - 1
                fields = '__all__'

        field_class = NestedRelationSerializer
        field_kwargs = get_nested_relation_kwargs(relation_info)

        return field_class, field_kwargs


class EmbeddedModelSerializer(DjongoModelSerializer):
    # Placeholder for the time being
    # TODO: Actually add this
    pass