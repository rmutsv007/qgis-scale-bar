# -*- coding: utf-8 -*-
"""
Custom Scale Bar Plugin for QGIS
Allows creating customizable scale bars in QGIS Print Layout with custom
irregular division intervals, detailed left-side subdivisions, and multiple styles.
"""


def classFactory(iface):
    from .plugin import CustomScaleBarPlugin
    return CustomScaleBarPlugin(iface)
