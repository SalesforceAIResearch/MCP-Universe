from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class FakeVector:
    values: tuple[float, float, float]

    def __init__(self, values: tuple[float, float, float] | list[float]):
        self.values = tuple(float(value) for value in values)

    @property
    def x(self) -> float:
        return self.values[0]

    @property
    def y(self) -> float:
        return self.values[1]

    @property
    def z(self) -> float:
        return self.values[2]


class FakeObject:
    def __init__(self, name: str = "Plane", object_type: str = "MESH"):
        self.name = name
        self.type = object_type
        self.location = FakeVector((0, 0, 0))
        self.rotation_euler = FakeVector((0, 0, 0))
        self.scale = FakeVector((1, 1, 1))
        self.data = types.SimpleNamespace(name=name)
        self.selected = False

    def select_set(self, selected: bool) -> None:
        self.selected = selected


class FakeViewLayer:
    def __init__(self) -> None:
        self.objects = types.SimpleNamespace(active=None)
        self.updated = False

    def update(self) -> None:
        self.updated = True


class FakeBpy(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("bpy")
        self.context = types.SimpleNamespace(view_layer=FakeViewLayer(), scene=types.SimpleNamespace(objects=[]))
        self.ops = types.SimpleNamespace(
            object=types.SimpleNamespace(
                select_all=self.select_all,
                empty_add=self.empty_add,
                camera_add=self.camera_add,
                light_add=self.light_add,
            ),
            mesh=types.SimpleNamespace(
                primitive_cube_add=self.primitive_cube_add,
                primitive_uv_sphere_add=self.primitive_uv_sphere_add,
                primitive_cylinder_add=self.primitive_cylinder_add,
                primitive_plane_add=self.primitive_plane_add,
                primitive_cone_add=self.primitive_cone_add,
            ),
        )
        self.types = types.SimpleNamespace(Panel=object, Scene=types.SimpleNamespace())
        self.props = types.SimpleNamespace(
            StringProperty=lambda **_kwargs: None,
            IntProperty=lambda **_kwargs: None,
            BoolProperty=lambda **_kwargs: None,
            EnumProperty=lambda **_kwargs: None,
        )
        self.utils = types.SimpleNamespace(register_class=lambda _cls: None, unregister_class=lambda _cls: None)
        self.app = types.SimpleNamespace(
            timers=types.SimpleNamespace(
                register=lambda *_args, **_kwargs: None,
                unregister=lambda *_args, **_kwargs: None,
                is_registered=lambda _fn: False,
            )
        )
        self.mesh_calls: dict[str, list[dict[str, Any]]] = {}
        self.object_calls: dict[str, list[dict[str, Any]]] = {}

    def select_all(self, **_kwargs: Any) -> None:
        return None

    def add_mesh_object(self, operator_name: str, **kwargs: Any) -> None:
        self.mesh_calls.setdefault(operator_name, []).append(kwargs)
        obj = FakeObject()
        obj.location = FakeVector(kwargs.get("location", (0, 0, 0)))
        obj.rotation_euler = FakeVector(kwargs.get("rotation", (0, 0, 0)))
        # Blender bakes the operator scale into mesh coordinates; object scale stays at identity.
        obj.scale = FakeVector((1, 1, 1))
        self.context.view_layer.objects.active = obj
        self.context.scene.objects.append(obj)

    def add_object(self, operator_name: str, object_type: str, **kwargs: Any) -> None:
        self.object_calls.setdefault(operator_name, []).append(kwargs)
        obj = FakeObject(object_type=object_type)
        obj.location = FakeVector(kwargs.get("location", (0, 0, 0)))
        obj.rotation_euler = FakeVector(kwargs.get("rotation", (0, 0, 0)))
        obj.scale = FakeVector((1, 1, 1))
        self.context.view_layer.objects.active = obj
        self.context.scene.objects.append(obj)

    def primitive_cube_add(self, **kwargs: Any) -> None:
        self.add_mesh_object("primitive_cube_add", **kwargs)

    def primitive_uv_sphere_add(self, **kwargs: Any) -> None:
        self.add_mesh_object("primitive_uv_sphere_add", **kwargs)

    def primitive_cylinder_add(self, **kwargs: Any) -> None:
        self.add_mesh_object("primitive_cylinder_add", **kwargs)

    def primitive_plane_add(self, **kwargs: Any) -> None:
        self.add_mesh_object("primitive_plane_add", **kwargs)

    def primitive_cone_add(self, **kwargs: Any) -> None:
        self.add_mesh_object("primitive_cone_add", **kwargs)

    def empty_add(self, **kwargs: Any) -> None:
        self.add_object("empty_add", "EMPTY", **kwargs)

    def camera_add(self, **kwargs: Any) -> None:
        self.add_object("camera_add", "CAMERA", **kwargs)

    def light_add(self, **kwargs: Any) -> None:
        self.add_object("light_add", "LIGHT", **kwargs)


def install_fake_blender_modules(monkeypatch):
    fake_bpy = FakeBpy()
    props_module = types.ModuleType("bpy.props")
    props_module.StringProperty = fake_bpy.props.StringProperty
    props_module.IntProperty = fake_bpy.props.IntProperty
    props_module.BoolProperty = fake_bpy.props.BoolProperty
    props_module.EnumProperty = fake_bpy.props.EnumProperty

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = FakeVector

    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    monkeypatch.setitem(sys.modules, "bpy.props", props_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))
    sys.modules.pop("blender_addon", None)
    return fake_bpy


@pytest.mark.parametrize(
    ("object_type", "operator_name"),
    [
        ("CUBE", "primitive_cube_add"),
        ("SPHERE", "primitive_uv_sphere_add"),
        ("CYLINDER", "primitive_cylinder_add"),
        ("PLANE", "primitive_plane_add"),
        ("CONE", "primitive_cone_add"),
    ],
)
def test_create_object_sets_mesh_scale_as_object_transform(monkeypatch, object_type: str, operator_name: str):
    fake_bpy = install_fake_blender_modules(monkeypatch)
    blender_addon = importlib.import_module("blender_addon")

    server = blender_addon.BlenderMCPServer()
    server._get_aabb = lambda _obj: [[0, 0, 0], [5, 5, 0]]

    result = server.create_object(type=object_type, name="ScaledObject", scale=(5, 5, 5))

    assert result["scale"] == [5, 5, 5]
    assert fake_bpy.context.view_layer.objects.active.scale.values == (5, 5, 5)
    assert "scale" not in fake_bpy.mesh_calls[operator_name][0]


@pytest.mark.parametrize(
    ("object_type", "operator_name"),
    [
        ("EMPTY", "empty_add"),
        ("CAMERA", "camera_add"),
        ("LIGHT", "light_add"),
    ],
)
def test_create_object_sets_non_mesh_scale_as_object_transform(monkeypatch, object_type: str, operator_name: str):
    fake_bpy = install_fake_blender_modules(monkeypatch)
    blender_addon = importlib.import_module("blender_addon")

    server = blender_addon.BlenderMCPServer()

    result = server.create_object(type=object_type, name="ScaledObject", scale=(0.5, 0.5, 0.5))

    assert result["scale"] == [0.5, 0.5, 0.5]
    assert fake_bpy.context.view_layer.objects.active.scale.values == (0.5, 0.5, 0.5)
    assert "scale" not in fake_bpy.object_calls[operator_name][0]
