import { AuthLayoutTitleProps } from "./types";

export default function AuthLayoutTitle(props: AuthLayoutTitleProps) {
    return <h2 className="font-semibold">{props.children}</h2>;
}
