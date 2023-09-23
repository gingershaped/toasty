import Handlebars from "handlebars";

declare module '*.handlebars' {
    const content: Handlebars.Template;
    export default content;
}