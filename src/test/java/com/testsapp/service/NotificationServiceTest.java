package com.testsapp.service;

import com.testsapp.domain.Appointment;
import com.testsapp.domain.NotificationChannel;
import com.testsapp.domain.NotificationMessage;
import com.testsapp.domain.NotificationType;
import com.testsapp.dto.NotificationResponse;
import com.testsapp.exception.ApiException;
import com.testsapp.repository.AppointmentRepository;
import com.testsapp.repository.NotificationRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class NotificationServiceTest {

    @Mock
    NotificationRepository notificationRepository;

    @Mock
    AppointmentRepository appointmentRepository;

    @InjectMocks
    NotificationService notificationService;

    private static final DateWindow FIXED_WINDOW = new DateWindow(
            LocalDateTime.of(2026, 9, 1, 10, 0),
            LocalDateTime.of(2026, 9, 1, 10, 30)
    );

    private record DateWindow(LocalDateTime start, LocalDateTime end) {
    }

    private Appointment scheduledAppointment(long id, String email, String customerName, LocalDateTime startTime) {
        Appointment appointment = new Appointment(
                1L,
                "Haircut",
                customerName,
                email,
                startTime,
                startTime.plusMinutes(30),
                BigDecimal.valueOf(100),
                null
        );
        appointment.assignId(id);
        return appointment;
    }

    private NotificationMessage notification(long id, long appointmentId, String email, String customerName, NotificationType type) {
        NotificationMessage message = new NotificationMessage(
                appointmentId,
                email,
                customerName,
                type,
                NotificationChannel.EMAIL,
                "subject-" + id,
                "content-" + id
        );
        message.assignId(id);
        return message;
    }

    // TC01
    @Test
    @DisplayName("listNotifications zwraca wszystkie rekordy, gdy customerEmail i appointmentId sa puste")
    void listNotificationsShouldReturnAllWhenNoFilters() {
        when(notificationRepository.findAll()).thenReturn(List.of(
                notification(1L, 1L, "john@example.com", "John", NotificationType.APPOINTMENT_CREATED),
                notification(2L, 2L, "jane@example.com", "Jane", NotificationType.APPOINTMENT_REMINDER),
                notification(3L, 3L, "mark@example.com", "Mark", NotificationType.APPOINTMENT_CANCELLED)
        ));

        List<NotificationResponse> result = notificationService.listNotifications(null, null);

        assertThat(result).hasSize(3);
    }

    // TC02
    @Test
    @DisplayName("listNotifications filtruje po customerEmail ignorujac wielkosc liter i biale znaki")
    void listNotificationsShouldFilterByTrimmedCaseInsensitiveEmail() {
        when(notificationRepository.findAll()).thenReturn(List.of(
                notification(1L, 1L, "john@example.com", "John", NotificationType.APPOINTMENT_CREATED),
                notification(2L, 2L, "jane@example.com", "Jane", NotificationType.APPOINTMENT_REMINDER),
                notification(3L, 3L, "JOHN@example.com", "John 2", NotificationType.APPOINTMENT_CANCELLED)
        ));

        List<NotificationResponse> result = notificationService.listNotifications("  JOHN@EXAMPLE.COM  ", null);

        assertThat(result).hasSize(2)
                .allMatch(item -> item.customerEmail().equalsIgnoreCase("john@example.com"));
    }

    // TC03
    @Test
    @DisplayName("listNotifications filtruje po appointmentId")
    void listNotificationsShouldFilterByAppointmentId() {
        when(notificationRepository.findAll()).thenReturn(List.of(
                notification(1L, 1L, "john@example.com", "John", NotificationType.APPOINTMENT_CREATED),
                notification(2L, 2L, "jane@example.com", "Jane", NotificationType.APPOINTMENT_REMINDER),
                notification(3L, 1L, "mark@example.com", "Mark", NotificationType.APPOINTMENT_CANCELLED)
        ));

        List<NotificationResponse> result = notificationService.listNotifications(null, 1L);

        assertThat(result).hasSize(2)
                .allMatch(item -> item.appointmentId() == 1L);
    }

    // TC04
    @Test
    @DisplayName("listNotifications stosuje oba filtry jednoczesnie (customerEmail i appointmentId)")
    void listNotificationsShouldApplyEmailAndAppointmentFiltersTogether() {
        when(notificationRepository.findAll()).thenReturn(List.of(
                notification(1L, 1L, "john@example.com", "John", NotificationType.APPOINTMENT_CREATED),
                notification(2L, 1L, "jane@example.com", "Jane", NotificationType.APPOINTMENT_REMINDER),
                notification(3L, 2L, "john@example.com", "John", NotificationType.APPOINTMENT_CANCELLED)
        ));

        List<NotificationResponse> result = notificationService.listNotifications("john@example.com", 1L);

        assertThat(result).hasSize(1);
        assertThat(result.get(0).customerEmail()).isEqualTo("john@example.com");
        assertThat(result.get(0).appointmentId()).isEqualTo(1L);
    }

    // TC05
    @Test
    @DisplayName("sendAppointmentCreatedNotification zapisuje EMAIL typu APPOINTMENT_CREATED z szablonem potwierdzenia")
    void sendAppointmentCreatedNotificationShouldPersistCreatedEmailMessage() {
        Appointment appointment = scheduledAppointment(11L, "john@example.com", "John", FIXED_WINDOW.start());
        when(notificationRepository.save(any(NotificationMessage.class))).thenAnswer(invocation -> {
            NotificationMessage message = invocation.getArgument(0);
            message.assignId(101L);
            return message;
        });

        NotificationResponse response = notificationService.sendAppointmentCreatedNotification(appointment);

        ArgumentCaptor<NotificationMessage> captor = ArgumentCaptor.forClass(NotificationMessage.class);
        verify(notificationRepository).save(captor.capture());
        NotificationMessage saved = captor.getValue();

        assertThat(saved.getType()).isEqualTo(NotificationType.APPOINTMENT_CREATED);
        assertThat(saved.getChannel()).isEqualTo(NotificationChannel.EMAIL);
        assertThat(saved.getSubject()).isEqualTo("Potwierdzenie wizyty #11");
        assertThat(saved.getContent()).contains("Twoja wizyta Haircut zostala zaplanowana na 2026-09-01 10:00.");
        assertThat(response.id()).isEqualTo(101L);
    }

    // TC06
    @Test
    @DisplayName("sendAppointmentCancelledNotification zapisuje EMAIL typu APPOINTMENT_CANCELLED z trescia anulowania")
    void sendAppointmentCancelledNotificationShouldPersistCancelledEmailMessage() {
        Appointment appointment = scheduledAppointment(12L, "john@example.com", "John", FIXED_WINDOW.start());
        when(notificationRepository.save(any(NotificationMessage.class))).thenAnswer(invocation -> {
            NotificationMessage message = invocation.getArgument(0);
            message.assignId(102L);
            return message;
        });

        NotificationResponse response = notificationService.sendAppointmentCancelledNotification(appointment);

        ArgumentCaptor<NotificationMessage> captor = ArgumentCaptor.forClass(NotificationMessage.class);
        verify(notificationRepository).save(captor.capture());
        NotificationMessage saved = captor.getValue();

        assertThat(saved.getType()).isEqualTo(NotificationType.APPOINTMENT_CANCELLED);
        assertThat(saved.getChannel()).isEqualTo(NotificationChannel.EMAIL);
        assertThat(saved.getSubject()).isEqualTo("Anulowanie wizyty #12");
        assertThat(saved.getContent()).contains("Wizyta Haircut zaplanowana na 2026-09-01 10:00 zostala anulowana.");
        assertThat(response.id()).isEqualTo(102L);
    }

    // TC07
    @Test
    @DisplayName("sendAppointmentRescheduledNotification zapisuje APPOINTMENT_RESCHEDULED i uwzglednia poprzedni oraz nowy termin")
    void sendAppointmentRescheduledNotificationShouldIncludePreviousAndNewTime() {
        LocalDateTime previous = LocalDateTime.of(2026, 9, 1, 9, 30);
        LocalDateTime current = LocalDateTime.of(2026, 9, 1, 11, 0);
        Appointment appointment = scheduledAppointment(13L, "john@example.com", "John", current);

        when(notificationRepository.save(any(NotificationMessage.class))).thenAnswer(invocation -> {
            NotificationMessage message = invocation.getArgument(0);
            message.assignId(103L);
            return message;
        });

        NotificationResponse response = notificationService.sendAppointmentRescheduledNotification(appointment, previous);

        ArgumentCaptor<NotificationMessage> captor = ArgumentCaptor.forClass(NotificationMessage.class);
        verify(notificationRepository).save(captor.capture());
        NotificationMessage saved = captor.getValue();

        assertThat(saved.getType()).isEqualTo(NotificationType.APPOINTMENT_RESCHEDULED);
        assertThat(saved.getSubject()).isEqualTo("Zmiana terminu wizyty #13");
        assertThat(saved.getContent()).contains("z 2026-09-01 09:30 na 2026-09-01 11:00");
        assertThat(response.id()).isEqualTo(103L);
    }

    // TC08
    @Test
    @DisplayName("sendReminderForAppointment dla istniejacej wizyty SCHEDULED zapisuje APPOINTMENT_REMINDER")
    void sendReminderForAppointmentShouldPersistReminderForScheduledAppointment() {
        Appointment appointment = scheduledAppointment(14L, "john@example.com", "John", FIXED_WINDOW.end());
        when(appointmentRepository.findById(14L)).thenReturn(Optional.of(appointment));
        when(notificationRepository.save(any(NotificationMessage.class))).thenAnswer(invocation -> {
            NotificationMessage message = invocation.getArgument(0);
            message.assignId(104L);
            return message;
        });

        NotificationResponse response = notificationService.sendReminderForAppointment(14L);

        assertThat(response.type()).isEqualTo(NotificationType.APPOINTMENT_REMINDER);
        assertThat(response.channel()).isEqualTo(NotificationChannel.EMAIL);
        assertThat(response.subject()).isEqualTo("Przypomnienie o wizycie #14");
    }

    // TC09
    @Test
    @DisplayName("sendReminderForAppointment rzuca ApiException NOT_FOUND, gdy appointmentId nie istnieje")
    void sendReminderForAppointmentShouldThrowNotFoundWhenAppointmentMissing() {
        when(appointmentRepository.findById(999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> notificationService.sendReminderForAppointment(999L))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus()).isEqualTo(HttpStatus.NOT_FOUND));
    }

    // TC10
    @Test
    @DisplayName("sendReminderForAppointment rzuca ApiException CONFLICT, gdy status wizyty nie jest SCHEDULED")
    void sendReminderForAppointmentShouldThrowConflictForNonScheduledStatus() {
        Appointment cancelled = scheduledAppointment(15L, "john@example.com", "John", FIXED_WINDOW.start());
        cancelled.cancel();
        when(appointmentRepository.findById(15L)).thenReturn(Optional.of(cancelled));

        assertThatThrownBy(() -> notificationService.sendReminderForAppointment(15L))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus()).isEqualTo(HttpStatus.CONFLICT));
    }

    // TC11
    @Test
    @DisplayName("dispatchUpcomingReminders uzywa horyzontu domyslnego 24h dla null/zero/ujemnego i liczy tylko wyslane przypomnienia")
    void dispatchUpcomingRemindersShouldUse24HoursForInvalidHorizon() {
        Appointment within = scheduledAppointment(201L, "john@example.com", "John", LocalDateTime.now().plusHours(1));
        when(appointmentRepository.findById(201L)).thenReturn(Optional.of(within));
        when(appointmentRepository.findUpcoming(any(LocalDateTime.class))).thenAnswer(invocation -> {
            LocalDateTime now = invocation.getArgument(0);
            Appointment in24h = scheduledAppointment(201L, "john@example.com", "John", now.plusHours(23));
            Appointment beyond24h = scheduledAppointment(202L, "jane@example.com", "Jane", now.plusHours(26));
            return List.of(in24h, beyond24h);
        });
        when(notificationRepository.hasReminderForAppointmentOnDate(eq(201L), any(LocalDate.class))).thenReturn(false);
        when(notificationRepository.save(any(NotificationMessage.class))).thenAnswer(invocation -> invocation.getArgument(0));

        int createdForNull = notificationService.dispatchUpcomingReminders(null);
        int createdForZero = notificationService.dispatchUpcomingReminders(Duration.ZERO);
        int createdForNegative = notificationService.dispatchUpcomingReminders(Duration.ofHours(-1));

        assertThat(createdForNull).isEqualTo(1);
        assertThat(createdForZero).isEqualTo(1);
        assertThat(createdForNegative).isEqualTo(1);
        verify(appointmentRepository, times(3)).findUpcoming(any(LocalDateTime.class));
        verify(notificationRepository, times(3)).save(any(NotificationMessage.class));
        verify(notificationRepository, never()).hasReminderForAppointmentOnDate(eq(202L), any(LocalDate.class));
    }

    // TC12
    @Test
    @DisplayName("dispatchUpcomingReminders pomija wizyty poza deadline (startTime po now+effectiveHorizon)")
    void dispatchUpcomingRemindersShouldSkipAppointmentsAfterDeadline() {
        Appointment within = scheduledAppointment(301L, "john@example.com", "John", LocalDateTime.now().plusHours(2));
        when(appointmentRepository.findById(301L)).thenReturn(Optional.of(within));
        when(appointmentRepository.findUpcoming(any(LocalDateTime.class))).thenAnswer(invocation -> {
            LocalDateTime now = invocation.getArgument(0);
            Appointment inDeadline = scheduledAppointment(301L, "john@example.com", "John", now.plusHours(2));
            Appointment afterDeadline = scheduledAppointment(302L, "jane@example.com", "Jane", now.plusHours(30));
            return List.of(inDeadline, afterDeadline);
        });
        when(notificationRepository.hasReminderForAppointmentOnDate(eq(301L), any(LocalDate.class))).thenReturn(false);
        when(notificationRepository.save(any(NotificationMessage.class))).thenAnswer(invocation -> invocation.getArgument(0));

        int created = notificationService.dispatchUpcomingReminders(Duration.ofHours(24));

        assertThat(created).isEqualTo(1);
        verify(notificationRepository).hasReminderForAppointmentOnDate(eq(301L), any(LocalDate.class));
        verify(notificationRepository, never()).hasReminderForAppointmentOnDate(eq(302L), any(LocalDate.class));
        verify(appointmentRepository, never()).findById(302L);
    }

    // TC13
    @Test
    @DisplayName("dispatchUpcomingReminders pomija wizyte, gdy reminder dla appointmentId istnieje juz dla biezacej daty")
    void dispatchUpcomingRemindersShouldSkipWhenReminderAlreadyExistsToday() {
        when(appointmentRepository.findUpcoming(any(LocalDateTime.class))).thenAnswer(invocation -> {
            LocalDateTime now = invocation.getArgument(0);
            Appointment inDeadline = scheduledAppointment(401L, "john@example.com", "John", now.plusHours(2));
            return List.of(inDeadline);
        });
        when(notificationRepository.hasReminderForAppointmentOnDate(eq(401L), any(LocalDate.class))).thenReturn(true);

        int created = notificationService.dispatchUpcomingReminders(Duration.ofHours(24));

        assertThat(created).isZero();
        verify(notificationRepository).hasReminderForAppointmentOnDate(eq(401L), any(LocalDate.class));
        verify(appointmentRepository, never()).findById(anyLong());
        verify(notificationRepository, never()).save(any(NotificationMessage.class));
    }
}

