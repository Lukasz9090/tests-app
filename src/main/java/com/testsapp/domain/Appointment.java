package com.testsapp.domain;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Objects;
public class Appointment {
    private long id;
    private final long serviceOfferId;
    private final String serviceName;
    private final String customerName;
    private final String customerEmail;
    private LocalDateTime startTime;
    private LocalDateTime endTime;
    private AppointmentStatus status;
    private BigDecimal price;
    private final String notes;
    private final LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    public Appointment(
            long serviceOfferId,
            String serviceName,
            String customerName,
            String customerEmail,
            LocalDateTime startTime,
            LocalDateTime endTime,
            BigDecimal price,
            String notes
    ) {
        this.serviceOfferId = serviceOfferId;
        this.serviceName = Objects.requireNonNull(serviceName, "serviceName");
        this.customerName = Objects.requireNonNull(customerName, "customerName");
        this.customerEmail = Objects.requireNonNull(customerEmail, "customerEmail");
        this.startTime = Objects.requireNonNull(startTime, "startTime");
        this.endTime = Objects.requireNonNull(endTime, "endTime");
        this.price = Objects.requireNonNull(price, "price");
        this.notes = notes == null ? "" : notes.trim();
        this.status = AppointmentStatus.SCHEDULED;
        this.createdAt = LocalDateTime.now();
        this.updatedAt = this.createdAt;
    }
    public long getId() {
        return id;
    }
    public long getServiceOfferId() {
        return serviceOfferId;
    }
    public String getServiceName() {
        return serviceName;
    }
    public String getCustomerName() {
        return customerName;
    }
    public String getCustomerEmail() {
        return customerEmail;
    }
    public LocalDateTime getStartTime() {
        return startTime;
    }
    public LocalDateTime getEndTime() {
        return endTime;
    }
    public AppointmentStatus getStatus() {
        return status;
    }
    public BigDecimal getPrice() {
        return price;
    }
    public String getNotes() {
        return notes;
    }
    public LocalDateTime getCreatedAt() {
        return createdAt;
    }
    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }
    public void assignId(long id) {
        if (this.id == 0) {
            this.id = id;
        }
    }
    public void cancel() {
        this.status = AppointmentStatus.CANCELLED;
        this.updatedAt = LocalDateTime.now();
    }
    public void complete() {
        this.status = AppointmentStatus.COMPLETED;
        this.updatedAt = LocalDateTime.now();
    }
    public void reschedule(LocalDateTime newStartTime, LocalDateTime newEndTime, BigDecimal newPrice) {
        this.startTime = Objects.requireNonNull(newStartTime, "newStartTime");
        this.endTime = Objects.requireNonNull(newEndTime, "newEndTime");
        this.price = Objects.requireNonNull(newPrice, "newPrice");
        this.status = AppointmentStatus.SCHEDULED;
        this.updatedAt = LocalDateTime.now();
    }
}
