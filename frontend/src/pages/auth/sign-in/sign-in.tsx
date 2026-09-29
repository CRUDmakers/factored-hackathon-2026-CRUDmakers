import { Button } from "@/components/ui/button";
import AuthLayoutContent from "@/layouts/auth/auth-layout-content";
import AuthLayoutTitle from "@/layouts/auth/auth-layout-title";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, Controller } from "react-hook-form";
import { useCallback, useId } from "react";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Trans } from "react-i18next";
import bankingCsAiApi from "@/services/api/banking-cs-ai.api";

export default function SignInPage() {
    const formSchema = z.object({ identity: z.string().nonempty(), password: z.string().nonempty() });
    type FormSchema = z.infer<typeof formSchema>;

    const indentityId = useId();
    const passwordId = useId();

    const form = useForm<FormSchema>({
        resolver: zodResolver(formSchema),
        defaultValues: {
            identity: "",
            password: "",
        },
    });

    const onSubmit = useCallback(async (data: FormSchema) => {
        await bankingCsAiApi.auth.signIn({ identity: data.identity, password: data.password });
        throw new Error("Not implemented yet");
    }, []);

    return (
        <AuthLayoutContent>
            <AuthLayoutTitle>
                <Trans ns={"auth"} i18nKey={"signIn.title"}>
                    Enter in your account
                </Trans>
            </AuthLayoutTitle>

            <form id="form-rhf-demo" onSubmit={form.handleSubmit(onSubmit)}>
                <FieldGroup>
                    <Controller
                        name="identity"
                        control={form.control}
                        render={({ field, fieldState }) => (
                            <Field data-invalid={fieldState.invalid}>
                                <FieldLabel htmlFor={indentityId}>
                                    <Trans ns={"auth"} i18nKey={"signIn.identity"}>
                                        Identity
                                    </Trans>
                                </FieldLabel>
                                <Input
                                    {...field}
                                    id={indentityId}
                                    aria-invalid={fieldState.invalid}
                                    placeholder="CLI-XXXXXXXXX"
                                    autoComplete="off"
                                />
                                {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                            </Field>
                        )}
                    />

                    <Controller
                        name="password"
                        control={form.control}
                        render={({ field, fieldState }) => (
                            <Field data-invalid={fieldState.invalid}>
                                <FieldLabel htmlFor={passwordId}>
                                    <Trans ns={"auth"} i18nKey={"signIn.password"}>
                                        Password
                                    </Trans>
                                </FieldLabel>
                                <Input
                                    {...field}
                                    id={passwordId}
                                    aria-invalid={fieldState.invalid}
                                    autoComplete="off"
                                    placeholder="********"
                                />
                                {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                            </Field>
                        )}
                    />
                </FieldGroup>
            </form>

            <Button size={"lg"} type="submit" form="form-rhf-demo" className={"w-full"}>
                {form.formState.isSubmitting ? (
                    <Trans ns={"common"} i18nKey={"loading"}>
                        Loading...
                    </Trans>
                ) : (
                    <Trans ns={"common"} i18nKey={"enter"}>
                        Enter
                    </Trans>
                )}
            </Button>
        </AuthLayoutContent>
    );
}
