export interface Position {
  line: number;
  character: number;
}

export interface Range {
  start: Position;
  end: Position;
}

export interface Location {
  url: string;
  range: Range;
}

export interface ImportInfo {
  url: string;
  location: Location;
}

export interface AnnotationInfo {
  route: string;
  text: string;
  content: string;
  location: Location;
}

export interface GivenInfo {
  name: string;
  type: string;
  required: boolean;
  default_text: string | null;
  location: Location | null;
  annotations: AnnotationInfo[];
}
