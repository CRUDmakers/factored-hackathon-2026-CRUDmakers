import { Button } from "@/components/ui/button";
import AuthLayoutContent from "@/layouts/auth/auth-layout-content";
import AuthLayoutTitle from "@/layouts/auth/auth-layout-title";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, Controller } from "react-hook-form";
import { useId } from "react";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Trans, useTranslation } from "react-i18next";
import bankingCsAiApi from "@/services/api/banking-cs-ai.api";
import useSafeCallback from "@/hooks/useSafeCallback";
import { useNavigate } from "react-router-dom";
import useSystem from "@/contexts/system/use-system";
import { TEST_CUSTOMERS } from "@/testCustomers";

export default function LoginPage() {
    const { t: tValid } = useTranslation("validation");
    const { language } = useSystem();

    const navigate = useNavigate();

    const customerIdId = useId();

    const formSchema = z.object({ customerId: z.string().nonempty(tValid("nonEmpty")) });
    type FormSchema = z.infer<typeof formSchema>;

    const form = useForm<FormSchema>({
        resolver: zodResolver(formSchema),
        defaultValues: { customerId: "" },
    });

    const onSubmit = useSafeCallback(async (data: FormSchema) => {
        await bankingCsAiApi.auth.login({ customerId: data.customerId });
        navigate("/session/home");
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
                        name="customerId"
                        control={form.control}
                        render={({ field, fieldState }) => (
                            <Field data-invalid={fieldState.invalid}>
                                <FieldLabel htmlFor={customerIdId}>
                                    <Trans ns={"auth"} i18nKey={"signIn.customerId"}>
                                        Customer ID
                                    </Trans>
                                </FieldLabel>
                                <Input
                                    {...field}
                                    id={customerIdId}
                                    aria-invalid={fieldState.invalid}
                                    placeholder="CLI-XXXXXXXXX"
                                    autoComplete="off"
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

            <div className="flex flex-col gap-2">
                <span className="text-muted-foreground text-sm">
                    <Trans ns={"auth"} i18nKey={"signIn.testCustomers"}>
                        Test customers
                    </Trans>
                </span>
                {TEST_CUSTOMERS.map((c) => (
                    <Button
                        key={c.id}
                        type="button"
                        variant="outline"
                        className="h-auto justify-start gap-3 py-2 text-left"
                        disabled={form.formState.isSubmitting}
                        onClick={() => {
                            form.setValue("customerId", c.id);
                            void form.handleSubmit(onSubmit)();
                        }}
                    >
                        <span className="text-muted-foreground w-6 text-xs font-semibold">{c.country}</span>
                        <span className="flex flex-col">
                            <strong className="text-sm">{c.name}</strong>
                            <span className="text-muted-foreground text-xs">
                                {c.id} · {c.note[language === "pt" ? "pt" : "es"]}
                            </span>
                        </span>
                    </Button>
                ))}
            </div>
        </AuthLayoutContent>
    );
}
