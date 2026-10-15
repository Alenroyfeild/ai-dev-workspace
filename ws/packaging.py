"""Small package metadata helpers; this module uses only the standard library."""


def package_version(version):
    """Translate the kit's beta SemVer to the equivalent PEP 440 version."""
    return version.replace('-beta.', 'b')
