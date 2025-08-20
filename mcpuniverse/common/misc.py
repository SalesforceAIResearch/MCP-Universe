"""
Helper functions and classes for component management and documentation inheritance.

This module provides utility classes for automatic docstring inheritance,
component registration, and configuration export.
"""
# pylint: disable=too-few-public-methods
import inspect
from abc import ABCMeta
from typing import Dict
from collections import defaultdict

_COMPONENTS = defaultdict(list)


class AutodocABCMeta(ABCMeta):
    """
    Metaclass for inheriting docstrings in abstract base classes.

    This metaclass ensures that inherited methods of an abstract base class
    also inherit the docstrings from their parent classes.
    """

    def __new__(mcs, classname, bases, cls_dict):
        cls = super().__new__(mcs, classname, bases, cls_dict)
        for name, member in cls_dict.items():
            if member.__doc__ is None:
                for base in bases[::-1]:
                    attr = getattr(base, name, None)
                    if attr is not None:
                        member.__doc__ = attr.__doc__
                        break
        return cls


class ComponentABCMeta(AutodocABCMeta):
    """
    Metaclass for component registration and docstring inheritance.

    This metaclass automatically registers non-abstract component classes
    in the `_COMPONENTS` dictionary and inherits docstrings from parent classes.
    """

    def __new__(mcs, classname, bases, cls_dict):
        cls = super().__new__(mcs, classname, bases, cls_dict)
        if not inspect.isabstract(cls):
            _module = cls.__module__.split(".")[1]
            _name = cls.__name__
            if _name in _COMPONENTS[_module]:
                raise RuntimeError(
                    f"Class name `{_name}` exists in `{_module}`. " f"Please use a different class name."
                )
            _COMPONENTS[_module].append(cls)
        return cls

    @staticmethod
    def get_class(module_name):
        """
        Retrieves registered classes for a given module.

        Args:
            module_name (str): The name of the module.

        Returns:
            list: A list of registered classes for the specified module.
        """
        return _COMPONENTS[module_name]


class BaseBuilder(metaclass=AutodocABCMeta):
    """
    Base class for builders.
    """

    @staticmethod
    def _name_to_class(classes):
        """
        Creates a mapping from class names and aliases to class objects.

        Args:
            classes (list): A list of class objects.

        Returns:
            dict: A dictionary mapping class names and aliases to class objects.

        Raises:
            AssertionError: If a duplicate alias is found.
        """
        name_to_class = {_class.__name__: _class for _class in classes}
        for _class in classes:
            if hasattr(_class, "alias"):
                if isinstance(_class.alias, (list, tuple)):
                    for name in _class.alias:
                        assert name not in name_to_class, f"Alias {name} exists, please use a different one."
                        name_to_class[name] = _class
                else:
                    assert (
                            _class.alias not in name_to_class
                    ), f"Alias {_class.alias} exists, please use a different one."
                    name_to_class[_class.alias] = _class
        return name_to_class


class ExportConfigMixin:
    """Mixin class for exporting model configurations."""

    def export_config(self) -> Dict:
        """
        Exports the model configuration as a dictionary.

        Returns:
            Dict: A dictionary containing the model's name and configuration.
                  The 'config' key will be None if the model has no 'config' attribute.
        """
        config = {"name": self.__class__.__name__}
        if hasattr(self, "config"):
            config["config"] = self.config.to_dict()
        else:
            config["config"] = None
        return config
