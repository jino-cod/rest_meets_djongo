import pytest


@pytest.fixture(scope='session')
def error_raised():
    """Builds a named tuple of error raising cases for use in tests"""
    from rest_framework.exceptions import ValidationError
    from pytest import raises

    return raises(ValidationError)


def pytest_configure():
    from django.conf import settings

    settings.configure(
        DEBUG=True,
        TEMPLATE_DEBUG=True,
        SECRET_KEY='T35TK3Y',
        DATABASES={
            'default': {
                'ENGINE': 'djongo',
                'NAME': 'test_db'
            }
        },
        INSTALLED_APPS=(
            'rest_framework',
            'rest_meets_djongo',
            'tests'
        )
    )

    try:
        import django
        django.setup()
    except AttributeError:
        pass
