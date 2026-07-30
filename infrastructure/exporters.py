import csv
import json


METADATA_COLUMNS = ["id", "source", "source_id", "layer", "name", "code", "description", "attributes_json"]
STANDARD_METADATA_KEYS = {"name", "code", "description", "layer", "color", "display_color"}


def _format_point(point):
    return "{:.3f}\t{:.3f}\t{:.3f}".format(point.x, point.y, point.z)


def _points_json(points):
    return json.dumps(
        [[float(point.x), float(point.y), float(point.z)] for point in points],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _clean_text(value):
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _property_value(measurement, key):
    properties = getattr(getattr(measurement, "properties", None), "values", {}) or {}
    return properties.get(key, "")


def _custom_attributes_json(measurement):
    properties = getattr(getattr(measurement, "properties", None), "values", {}) or {}
    attributes = {
        key: value
        for key, value in properties.items()
        if key not in STANDARD_METADATA_KEYS
    }
    return json.dumps(attributes, ensure_ascii=False, sort_keys=True)


def _raw_metadata_values(measurement):
    return [
        _clean_text(_property_value(measurement, "name")),
        _clean_text(getattr(measurement, "layer", "")),
        _clean_text(_property_value(measurement, "code")),
        _clean_text(_property_value(measurement, "description")),
        _clean_text(_custom_attributes_json(measurement)),
    ]


def _record_metadata_values(record):
    return [
        _clean_text(getattr(record, "id", "")),
        _clean_text(getattr(record, "source", "")),
        _clean_text(getattr(record, "source_id", "")),
        _clean_text(getattr(record, "layer", "")),
        _clean_text(_property_value(record, "name")),
        _clean_text(_property_value(record, "code")),
        _clean_text(_property_value(record, "description")),
        _clean_text(_custom_attributes_json(record)),
    ]


class RawEdgeTxtWriter:
    def write(self, filename, measurements):
        measurements = tuple(measurements)
        with open(filename, "w", encoding="utf-8") as file:
            file.write("EDGES POINTS {}\n".format(len(measurements)))
            for measurement in measurements:
                if len(measurement.points) >= 2:
                    file.write(
                        "{}\t{}\t{}\n".format(
                            _format_point(measurement.points[0]),
                            _format_point(measurement.points[1]),
                            "\t".join(_raw_metadata_values(measurement)),
                        )
                    )


class RawFaceTxtWriter:
    def write(self, filename, measurements):
        measurements = tuple(measurements)
        with open(filename, "w", encoding="utf-8") as file:
            file.write("FACES POINTS {}\n".format(len(measurements)))
            for measurement in measurements:
                if len(measurement.points) >= 3:
                    file.write(
                        "{}\t{}\t{}\t{}\t{}\t{}\n".format(
                            _format_point(measurement.points[0]),
                            _format_point(measurement.points[1]),
                            _format_point(measurement.points[2]),
                            "\t".join(_raw_metadata_values(measurement)),
                            len(measurement.points),
                            _points_json(measurement.points),
                        )
                    )


class ProcessedEdgeCsvWriter:
    def write(self, filename, records):
        with open(filename, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=",")
            writer.writerow([
                "x",
                "y",
                "z",
                "azimuth",
                "dip",
                "edge_azimuth",
                "edge_dip",
                "rotated_azimuth",
                "length",
                *METADATA_COLUMNS,
            ])
            for record in records:
                line = record.line_orientation
                edge = record.edge_orientation
                writer.writerow([
                    record.center.x,
                    record.center.y,
                    record.center.z,
                    line.azimuth,
                    line.dip,
                    edge.azimuth,
                    edge.dip,
                    line.rotated_azimuth,
                    record.length,
                    *_record_metadata_values(record),
                ])


class ProcessedTraceCsvWriter:
    """One row per trace, describing how its total length is made up.

    ``length`` is the sum of the segments and ``span_length`` the straight
    distance between the ends; their ratio, ``sinuosity``, is how far the trace
    wanders from that straight line.
    """

    def write(self, filename, records):
        with open(filename, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=",")
            writer.writerow([
                "x",
                "y",
                "z",
                "length",
                "segment_count",
                "mean_segment_length",
                "min_segment_length",
                "max_segment_length",
                "span_length",
                "sinuosity",
                "azimuth",
                "plunge",
                "rotated_azimuth",
                "point_count",
                *METADATA_COLUMNS,
            ])
            for record in records:
                line = record.line_orientation
                segments = tuple(record.segment_lengths or ())
                span = record.span_length or 0.0
                writer.writerow([
                    record.center.x,
                    record.center.y,
                    record.center.z,
                    record.length,
                    record.segment_count,
                    record.mean_segment_length,
                    min(segments) if segments else None,
                    max(segments) if segments else None,
                    record.span_length,
                    (record.length / span) if span else None,
                    line.azimuth if line is not None else None,
                    line.dip if line is not None else None,
                    line.rotated_azimuth if line is not None else None,
                    len(record.points),
                    *_record_metadata_values(record),
                ])


class ProcessedFaceCsvWriter:
    def write(self, filename, records):
        with open(filename, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=",")
            writer.writerow([
                "x",
                "y",
                "z",
                "azimuth",
                "dip",
                "rotated_azimuth",
                "area",
                "degree",
                "point_count",
                "fit_error",
                "fit_error_relative",
                "degeneracy",
                *METADATA_COLUMNS,
            ])
            for record in records:
                plane = record.plane_orientation
                writer.writerow([
                    record.center.x,
                    record.center.y,
                    record.center.z,
                    plane.azimuth,
                    plane.dip,
                    plane.rotated_azimuth,
                    record.area,
                    record.degree,
                    len(record.points),
                    record.fit_error,
                    record.fit_error_relative,
                    _clean_text(getattr(record, "degeneracy", "")),
                    *_record_metadata_values(record),
                ])
