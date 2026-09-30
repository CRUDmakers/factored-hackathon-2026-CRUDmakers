import { AuthLayoutContentProps } from "./types";

export default function AuthLayoutContent(props: AuthLayoutContentProps) {
    return <div className="flex flex-col gap-3">{props.children}</div>;
}
