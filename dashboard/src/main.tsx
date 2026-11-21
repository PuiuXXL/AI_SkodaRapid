import {createRoot} from "react-dom/client";
import App from "./App";
import "./fluid.css"; // loaded last: the visual layer over the older stylesheets

createRoot(document.getElementById("root")!).render(<App/>);
