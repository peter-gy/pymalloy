/** @title SourcePosition */
export interface SourcePosition {
  /** @asType integer @minimum 0 */
  line: number;
  /** @asType integer @minimum 0 */
  character: number;
}

/** @title SourceRange */
export interface SourceRange {
  start: SourcePosition;
  end: SourcePosition;
}

/** @title SourceLocation */
export interface SourceLocation {
  url: string;
  range: SourceRange;
}

/** @title ImportInfo */
export interface ImportInfo {
  url: string;
  location: SourceLocation;
}

/** @title AnnotationInfo */
export interface AnnotationInfo {
  route: string;
  text: string;
  content: string;
  location: SourceLocation;
}

/** @title GivenInfo */
export interface GivenInfo {
  name: string;
  type: string;
  required: boolean;
  defaultText: string | null;
  location: SourceLocation | null;
  annotations: AnnotationInfo[];
}
