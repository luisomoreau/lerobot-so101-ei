declare module "urdf-loader/src/urdf-manipulator-element.js" {
  const URDFManipulator: CustomElementConstructor;
  export default URDFManipulator;
}

declare namespace JSX {
  interface IntrinsicElements {
    "urdf-viewer": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement>;
  }
}
