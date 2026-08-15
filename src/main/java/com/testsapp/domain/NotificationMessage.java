package com.testsapp.domain;

import java.time.LocalDateTime;
import java.util.Objects;

public class NotificationMessage {
    private long id;
    private final long appointmentId;
    private final String customerEmail;
    private final String customerName;
    private final NotificationType type;
    private final NotificationChannel channel;
    private final String subject;
    private final String content;
    private final LocalDateTime createdAt;

    public NotificationMessage(
            long appointmentId,
            String customerEmail,
            String customerName,
            NotificationType type,
            NotificationChannel channel,
            String subject,
            String content
    ) {
        this.appointmentId = appointmentId;
        this.customerEmail = Objects.requireNonNull(customerEmail, "customerEmail");
        this.customerName = Objects.requireNonNull(customerName, "customerName");
        this.type = Objects.requireNonNull(type, "type");
        this.channel = Objects.requireNonNull(channel, "channel");
        this.subject = Objects.requireNonNull(subject, "subject");
        this.content = Objects.requireNonNull(content, "content");
        this.createdAt = LocalDateTime.now();
    }

    public long getId() {
        return id;
    }

    public long getAppointmentId() {
        return appointmentId;
    }

    public String getCustomerEmail() {
        return customerEmail;
    }

    public String getCustomerName() {
        return customerName;
    }

    public NotificationType getType() {
        return type;
    }

    public NotificationChannel getChannel() {
        return channel;
    }

    public String getSubject() {
        return subject;
    }

    public String getContent() {
        return content;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void assignId(long id) {
        if (this.id == 0) {
            this.id = id;
        }
    }
}

